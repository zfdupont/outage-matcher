"""Generate evals/results/summary.md and evals/baseline.json from the recorded result files.

    uv run python -m outage_matcher.evals.summary

Every number in the summary is read from a result file; nothing is computed from outside them
except differences between recorded runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from outage_matcher.evals.faithfulness import (
    abstained_after_dropped_citation,
    abstained_with_relevant_chunks,
)
from outage_matcher.evals.metrics import KS
from outage_matcher.evals.run_faithfulness import OUT_NAME as FAITHFULNESS_FILE
from outage_matcher.evals.run_retrieval import RESULTS_DIR

# Both runs made with the answer prompt that listed excerpts as `[0] doc_id=...`, oldest first.
EARLIER_FAITHFULNESS_FILES = (
    "faithfulness-prefix-bug-first-run.json",
    "faithfulness-prefix-bug.json",
)
SUMMARY_PATH = RESULTS_DIR / "summary.md"
BASELINE_PATH = Path("evals/baseline.json")
DEFAULT_TOLERANCE = 0.05  # 1.7 gold queries of recall@k (1 query = 1/34): one flip passes
METRIC_KEYS = [f"recall@{k}" for k in KS] + ["mrr"]


@dataclass(frozen=True)
class Run:
    name: str
    data: dict[str, Any]

    @property
    def config(self) -> dict[str, Any]:
        return self.data["config"]

    @property
    def metrics(self) -> dict[str, float]:
        return self.data["metrics"]

    @property
    def ranks(self) -> dict[str, int | None]:
        return {q["id"]: q["rank"] for q in self.data["per_query"]}


def load_runs(results_dir: Path) -> tuple[list[Run], dict[str, Any] | None]:
    """Retrieval runs (sorted by name) and the faithfulness result, if recorded."""
    runs = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name.startswith("faithfulness"):  # the current run and the earlier ones
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.append(Run(data.get("run", path.stem), data))
    faithfulness = results_dir / FAITHFULNESS_FILE
    return runs, json.loads(faithfulness.read_text()) if faithfulness.exists() else None


def load_earlier_faithfulness(results_dir: Path) -> list[dict[str, Any]]:
    """The recorded runs made before the answer-prompt fix that exist in `results_dir`."""
    paths = [results_dir / name for name in EARLIER_FAITHFULNESS_FILES]
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths if p.exists()]


def check_comparable(
    runs: list[Run],
    faithfulness: dict[str, Any] | None = None,
    earlier: Sequence[dict[str, Any]] = (),
) -> None:
    """Results are only reported together when they scored the same gold set on the same index.
    The faithfulness result counts too: it must match the retrieval runs."""
    documents = [r.data for r in runs] + [d for d in (faithfulness, *earlier) if d is not None]
    gold = {d["gold"]["sha256"] for d in documents}
    index = {d["index"]["version"] for d in documents}
    if len(gold) > 1 or len(index) > 1:
        raise ValueError(
            f"result files differ in gold set ({len(gold)} versions) or index "
            f"({len(index)} versions); rerun the stale ones"
        )


def pick_baseline(runs: list[Run]) -> Run:
    """The better embedding model under plain section chunking: highest MRR, then recall@5."""
    plain = [r for r in runs if r.config["chunking"] == "section" and not r.config["reranker"]]
    if not plain:
        raise ValueError("no section-chunking run without a reranker to use as the baseline")
    return max(plain, key=lambda r: (r.metrics["mrr"], r.metrics["recall@5"]))


def compare_ranks(base: Run, other: Run) -> tuple[int, int, int]:
    """Queries where `other` ranks the source document better, worse, or equally."""
    better = worse = same = 0
    for query_id, base_rank in base.ranks.items():
        a = base_rank if base_rank is not None else float("inf")
        b = other.ranks[query_id] if other.ranks[query_id] is not None else float("inf")
        better += b < a
        worse += b > a
        same += b == a
    return better, worse, same


def config_label(run: Run) -> str:
    cfg = run.config
    parts = [cfg["embedding_model"], f"{cfg['chunking']} chunking"]
    if cfg["reranker"]:
        parts.append(f"rerank {cfg['reranker']} (top {cfg['rerank_depth']})")
    return ", ".join(parts)


def _metric_cells(metrics: dict[str, float]) -> str:
    return " | ".join(f"{metrics[key]:.3f}" for key in METRIC_KEYS)


def _header(first: str, extra: Sequence[str] = ()) -> list[str]:
    columns = [first, *[f"recall@{k}" for k in KS], "MRR", *extra]
    return ["| " + " | ".join(columns) + " |", "|" + " --- |" * len(columns)]


def render_summary(
    runs: list[Run],
    faithfulness: dict[str, Any] | None,
    earlier: Sequence[dict[str, Any]] = (),
) -> str:
    check_comparable(runs, faithfulness, earlier)
    baseline = pick_baseline(runs)
    first = baseline.data
    lines = [
        "# Eval results",
        "",
        "Generated by `uv run python -m outage_matcher.evals.summary` from the files in "
        "`evals/results/`. Do not edit by hand.",
        "",
        f"- Gold set: {first['gold']['queries']} synthetic queries, `{first['gold']['path']}` "
        f"(sha256 {first['gold']['sha256'][:12]}), generated by "
        f"{first['gold']['generation']['model']} on {first['gold']['generation']['date']}.",
        f"- Index: version {first['index']['version']}, {first['index']['documents']} "
        f"documents, {first['index']['chunks']} chunks.",
        "- Rank is the position of the source document among distinct documents (a document sits "
        "where its best chunk does); each query's held-out root-cause chunks are excluded.",
        f"- With {first['gold']['queries']} queries one query moves recall@k by "
        f"{1 / first['gold']['queries']:.3f}; small differences are within noise.",
        "",
        "## Embedding models (section chunking)",
        "",
        *_header("Model"),
    ]
    for run in runs:
        if run.config["chunking"] == "section" and not run.config["reranker"]:
            lines.append(
                f"| {run.config['embedding_model']} ({run.config['embedding_model_name']}) | "
                f"{_metric_cells(run.metrics)} |"
            )
    lines += [
        "",
        f"Baseline: **{config_label(baseline)}** (highest MRR of the models above).",
        "",
        "## Improvements on the identical gold set",
        "",
        *_header("Configuration", ["vs baseline MRR", "better / worse / same queries"]),
    ]
    model = baseline.config["embedding_model"]
    candidates = [r for r in runs if r.config["embedding_model"] == model]
    ordered = [baseline] + [r for r in candidates if r is not baseline]
    for run in ordered:
        if run is baseline:
            extra = "baseline | -"
        else:
            better, worse, same = compare_ranks(baseline, run)
            delta = run.metrics["mrr"] - baseline.metrics["mrr"]
            extra = f"{delta:+.3f} | {better} / {worse} / {same}"
        lines.append(f"| {config_label(run)} | {_metric_cells(run.metrics)} | {extra} |")
    if faithfulness is not None:
        lines += _render_faithfulness(faithfulness)
        if earlier:
            lines += _render_earlier(faithfulness, list(earlier))
    lines.append("")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _abstention_breakdown(per_query: list[dict[str, Any]]) -> tuple[int, list[str], int]:
    """Abstentions split into: dropped citation, relevant chunks but no valid citation (ids),
    and no relevant retrieval."""
    abstained = [q for q in per_query if q.get("no_match")]
    dropped = sum(1 for q in abstained if abstained_after_dropped_citation(q))
    unexplained = [q["id"] for q in abstained if abstained_with_relevant_chunks(q)]
    return dropped, unexplained, len(abstained) - dropped - len(unexplained)


def _render_faithfulness(data: dict[str, Any]) -> list[str]:
    m, cfg, tokens = data["metrics"], data["config"], data["tokens"]
    dropped, unexplained, none_relevant = _abstention_breakdown(data["per_query"])
    thinking = cfg.get("judge_thinking")
    lines = [
        "",
        "## Faithfulness (LLM judge)",
        "",
        f"- Agent: {cfg['agent_model']} (Anthropic). Judge: {cfg['judge_model']} (DeepSeek, a "
        f"different model family), temperature {cfg['judge_temperature']}"
        + (f", thinking {thinking}" if thinking else "")
        + f". Run on {data['date']}. A single run of a nondeterministic agent.",
        f"- Queries: {m['queries']}; judged answers: {m['answered_and_judged']}; abstained "
        f"(no close match): {m['no_match']}; errors: {m['errors']}. The rates below cover only "
        f"the {m['answered_and_judged']} judged answers; abstentions are not scored.",
        f"- Abstentions: {dropped} of {dropped + len(unexplained) + none_relevant} followed "
        f"citations that were all dropped by the citation check (a cited document that was not "
        f"retrieved); {len(unexplained)} "
        f"had relevant chunks but no valid citation or text ({', '.join(unexplained) or 'none'}), "
        f"cause not explained; {none_relevant} had no relevant retrieval.",
        f"- Claims supported by the cited chunks: {m['claims_supported']} of {m['claims']} "
        f"({_fmt(m['claim_support_rate'])}).",
        f"- Answers with every claim supported: {_fmt(m['faithful_answer_rate'])}.",
        f"- Tokens: agent {tokens['agent']['input_tokens']} in / "
        f"{tokens['agent']['output_tokens']} out, judge {tokens['judge']['input_tokens']} in / "
        f"{tokens['judge']['output_tokens']} out.",
    ]
    return lines


def _span(values: list[float | int | None], fmt: str = "{}") -> str:
    present = [v for v in values if v is not None]
    low, high = min(present), max(present)
    return fmt.format(low) if low == high else f"{fmt.format(low)} to {fmt.format(high)}"


def _render_earlier(now: dict[str, Any], before: list[dict[str, Any]]) -> list[str]:
    """Before/after of the answer-prompt fix: same gold set, judge and index, single runs."""
    old = [d["metrics"] for d in before]
    new = now["metrics"]
    dropped_note = [
        f"{_abstention_breakdown(d['per_query'])[0]} of {d['metrics']['no_match']} in `{name}`"
        for d, name in zip(before, EARLIER_FAITHFULNESS_FILES[-len(before) :], strict=True)
        if any("answer_notes" in q for q in d["per_query"])
    ]
    unrecorded = any("answer_notes" not in q for d in before for q in d["per_query"])
    after_dropped = _abstention_breakdown(now["per_query"])[0]
    lines = [
        "",
        "### Before and after the citation-prompt fix",
        "",
        f"Every row is one run on the same gold set, index and judge; the agent is "
        f"nondeterministic, so each row is a single draw. {len(before)} runs were made with the "
        "earlier answer prompt, which listed excerpts as `[0] doc_id=...`; the model often cited "
        "the position instead of the doc_id and the citation check turned those answers into "
        "abstentions. The current run labels excerpts by doc_id only.",
        "",
        "| Run | answers judged | abstained | claims supported | claim support | "
        "answers with every claim supported |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    names = ["before the fix, first run", "before the fix, second run"][-len(before) :]
    for label, d in zip(names, before, strict=True):
        lines.append(_faith_row(label, d["date"], d["metrics"]))
    lines.append(_faith_row("after the fix", now["date"], new))
    lines += [
        "",
        "The answered sets differ in size "
        f"({', '.join(str(m['answered_and_judged']) for m in [*old, new])} answers), and "
        "abstentions are excluded from the rates, so the rates are not like-for-like.",
        "",
        "Differences in claim support and in all-claims-supported between the earlier runs and "
        f"the current one (claim support {_span([m['claim_support_rate'] for m in old], '{:.3f}')} "
        f"before, {_fmt(new['claim_support_rate'])} after; all-claims-supported "
        f"{_span([m['faithful_answer_rate'] for m in old], '{:.3f}')} before, "
        f"{_fmt(new['faithful_answer_rate'])} after) are within the run-to-run noise of single "
        f"nondeterministic runs; the earlier runs alone abstained on "
        f"{_span([m['no_match'] for m in old])} queries.",
        "",
        "The only clear effect of the fix is fewer abstentions: the abstentions after dropped "
        f"citations were {'; '.join(dropped_note) or 'not recorded'} before the fix and "
        f"{after_dropped} of {new['no_match']} after it."
        + (" Runs without per-answer notes cannot be counted." if unrecorded else ""),
    ]
    return lines


def _faith_row(label: str, date: str, m: dict[str, Any]) -> str:
    return (
        f"| {label} ({date}) | {m['answered_and_judged']} of {m['queries']} | {m['no_match']} | "
        f"{m['claims_supported']} of {m['claims']} | {_fmt(m['claim_support_rate'])} | "
        f"{_fmt(m['faithful_answer_rate'])} |"
    )


def baseline_document(run: Run, tolerance: float) -> dict[str, Any]:
    return {
        "run": run.name,
        "config": run.config,
        "gold_sha256": run.data["gold"]["sha256"],
        "gold_queries": run.data["gold"]["queries"],
        "index_version": run.data["index"]["version"],
        "index_documents": run.data["index"]["documents"],
        "index_chunks": run.data["index"]["chunks"],
        "recorded": run.data["date"],
        "metrics": {key: run.metrics[key] for key in METRIC_KEYS},
        "tolerance": tolerance,
        "rule": "fail when any metric is below its baseline value minus the tolerance "
        "(absolute, on the same gold set); "
        "see src/outage_matcher/evals/gate.py for the index checks",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="summary", description=__doc__.split("\n\n")[0])
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--baseline-out", type=Path, default=BASELINE_PATH)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)
    runs, faithfulness = load_runs(args.results_dir)
    earlier = load_earlier_faithfulness(args.results_dir)
    try:
        text = render_summary(runs, faithfulness, earlier)
        baseline = baseline_document(pick_baseline(runs), args.tolerance)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.out.write_text(text, encoding="utf-8")
    args.baseline_out.parent.mkdir(parents=True, exist_ok=True)
    args.baseline_out.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} and {args.baseline_out} (baseline run {baseline['run']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
