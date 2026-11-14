"""Regression gate for the retrieval eval, the same check CI runs (`.github/workflows/eval.yml`).

    uv run python -m outage_matcher.evals.gate index           # can the index be scored?
    uv run python -m outage_matcher.evals.gate compare RESULT  # did recall@k or MRR drop?

`evals/baseline.json` stores the baseline metrics, the index version and counts and gold set they
were measured on, and a tolerance. The rule:

1. Hard failure, with the instructions to refresh the baseline, only when the fresh index is
   structurally incompatible with the gold set: a gold held-out chunk id or relevant document id is
   missing from it, a gold chunk id points at another document, URL or position than the gold
   row's (serial ids shift when a page changes its chunk count), or its document or chunk count is
   more than 2 percent away from the baseline's.
2. Otherwise recall@k and MRR are compared with the baseline and the gate fails when any is more
   than the tolerance below its baseline value.
3. A different index version alone (a page changed a little, for example a view counter) only
   prints a WARNING with the old and new version; the gate still passes if the metrics are within
   tolerance.

A different gold set file or run configuration is also a failure: those scores are not comparable.

Exit code 0: pass; 1: fail; 2: a file is missing or unreadable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from outage_matcher import db
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals.gold import GOLD_PATH, GoldQuery, read_gold
from outage_matcher.evals.summary import BASELINE_PATH, METRIC_KEYS

EPSILON = 1e-9  # a score exactly at the floor passes; this absorbs float rounding
MAX_COUNT_DRIFT = 0.02  # relative change of the document or chunk count that is still comparable
MAX_LISTED = 10  # ids named in a message

REFRESH_HELP = (
    "If the change is intended, refresh the baseline: rebuild the gold set "
    "(`uv run python evals/build_gold.py`), rerun the retrieval evals in evals/results/, run "
    "`uv run python -m outage_matcher.evals.summary` and commit evals/baseline.json "
    "and evals/gold.jsonl. Otherwise check the fetch step of the job for pages that could not "
    "be fetched."
)


@dataclass(frozen=True)
class MetricCheck:
    name: str
    baseline: float
    floor: float
    current: float

    @property
    def passed(self) -> bool:
        return self.current >= self.floor - EPSILON


@dataclass(frozen=True)
class GateResult:
    errors: list[str]  # hard failures: the result cannot be compared with the baseline
    warnings: list[str] = field(default_factory=list)  # printed, never fail the gate
    checks: list[MetricCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors and all(c.passed for c in self.checks)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _listed(ids: Iterable[int]) -> str:
    ordered = sorted(ids)
    text = ", ".join(str(i) for i in ordered[:MAX_LISTED])
    return text + (f" and {len(ordered) - MAX_LISTED} more" if len(ordered) > MAX_LISTED else "")


def count_drift(documents: int, chunks: int, baseline: dict[str, Any]) -> list[str]:
    """Problems when the document or chunk count moved more than 2 percent from the baseline's."""
    problems = []
    for label, now, then in (
        ("document", documents, baseline["index_documents"]),
        ("chunk", chunks, baseline["index_chunks"]),
    ):
        change = abs(now - then) / then if then else float("inf")
        if change > MAX_COUNT_DRIFT:
            problems.append(
                f"the index has {now} {label}s but the baseline's has {then} "
                f"({change:.1%} change, more than {MAX_COUNT_DRIFT:.0%})"
            )
    return problems


def gold_ids(gold: Sequence[GoldQuery]) -> tuple[set[int], set[int]]:
    """Every held-out chunk id and every relevant document id the gold set refers to."""
    chunk_ids = {i for row in gold for i in row.held_out_chunk_ids}
    doc_ids = {i for row in gold for i in row.relevant_doc_ids}
    return chunk_ids, doc_ids


@dataclass(frozen=True)
class ChunkRow:
    """Where a gold chunk id points in the index: its document, the document's URL and position."""

    doc_id: int
    url: str
    ord: int


def structural_problems(
    gold: Sequence[GoldQuery],
    chunk_rows: dict[int, ChunkRow],
    present_doc_ids: set[int],
    documents: int,
    chunks: int,
    baseline: dict[str, Any],
) -> list[str]:
    """Why the index cannot be scored with this gold set (empty when it can).

    Chunk ids are serial numbers, so a page that gains or loses a chunk shifts every later id and
    an id can exist yet name another chunk. Each gold chunk must therefore belong to the gold
    row's document (same id and URL) at one of the row's held-out positions.
    """
    chunk_ids, doc_ids = gold_ids(gold)
    problems = []
    missing = chunk_ids - set(chunk_rows)
    if missing:
        problems.append(f"gold held-out chunk ids missing from the index: {_listed(missing)}")
    misaligned = []
    for row in gold:
        for chunk_id in row.held_out_chunk_ids:
            found = chunk_rows.get(chunk_id)
            if found is None:
                continue  # already reported as missing
            if (
                found.doc_id != row.doc_id
                or found.url != row.doc_url
                or found.ord not in row.held_out_ords
            ):
                misaligned.append(f"{row.id} chunk {chunk_id}")
    if misaligned:
        problems.append(
            "gold held-out chunk ids that now point at another document or position "
            f"(ids shifted): {', '.join(misaligned[:MAX_LISTED])}"
            + (f" and {len(misaligned) - MAX_LISTED} more" if len(misaligned) > MAX_LISTED else "")
        )
    missing_docs = doc_ids - present_doc_ids
    if missing_docs:
        problems.append(
            f"gold relevant document ids missing from the index: {_listed(missing_docs)}"
        )
    return problems + count_drift(documents, chunks, baseline)


def version_warning(version: str, baseline: dict[str, Any]) -> str | None:
    """A warning when the index is not byte-identical to the one the baseline was recorded on."""
    if version == baseline["index_version"]:
        return None
    return (
        f"index version {version} differs from the baseline's {baseline['index_version']}: some "
        "page content changed since the baseline was recorded (for example a view counter). The "
        "gold ids and counts are compatible, so the metrics are compared anyway. Refresh the "
        "baseline when convenient."
    )


def _structural_error(problems: list[str]) -> str:
    return (
        "the index is not compatible with the gold set: "
        + "; ".join(problems)
        + ". "
        + REFRESH_HELP
    )


def compare(result: dict[str, Any], baseline: dict[str, Any]) -> GateResult:
    """Check one retrieval result file against the baseline."""
    errors: list[str] = []
    drift = count_drift(result["index"]["documents"], result["index"]["chunks"], baseline)
    if drift:
        errors.append(_structural_error(drift))
    if result["gold"]["sha256"] != baseline["gold_sha256"]:
        errors.append(
            "the gold set differs from the one the baseline was measured on "
            f"(sha256 {result['gold']['sha256'][:12]} vs {baseline['gold_sha256'][:12]}). "
            + REFRESH_HELP
        )
    for key in ("embedding_model", "chunking", "reranker"):
        if result["config"].get(key) != baseline["config"].get(key):
            errors.append(
                f"the run's {key} is {result['config'].get(key)!r} but the baseline's is "
                f"{baseline['config'].get(key)!r}; run the same configuration as the baseline"
            )
    warning = version_warning(result["index"]["version"], baseline)
    tolerance = baseline["tolerance"]
    checks = [
        MetricCheck(
            key,
            baseline["metrics"][key],
            baseline["metrics"][key] - tolerance,
            result["metrics"][key],
        )
        for key in METRIC_KEYS
    ]
    return GateResult(errors, [warning] if warning else [], checks)


def render(result: GateResult, tolerance: float, baseline_run: str) -> str:
    lines = [
        f"Retrieval gate against baseline run `{baseline_run}` (tolerance {tolerance}, absolute)",
        "",
        "| metric | baseline | floor | current | status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in result.checks:
        status = "ok" if c.passed else "REGRESSED"
        lines.append(
            f"| {c.name} | {c.baseline:.3f} | {c.floor:.3f} | {c.current:.3f} | {status} |"
        )
    lines.append("")
    lines += [f"WARNING: {w}" for w in result.warnings]
    if result.errors:
        lines += [f"FAIL: {e}" for e in result.errors]
    elif not result.passed:
        names = ", ".join(c.name for c in result.checks if not c.passed)
        lines.append(f"FAIL: {names} dropped more than {tolerance} below the baseline.")
    else:
        lines.append("PASS: no metric dropped more than the tolerance.")
    return "\n".join(lines)


def _annotate_warnings(warnings: Iterable[str]) -> None:
    """Show a warning in the GitHub Actions UI as well as in the log."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for warning in warnings:
            print(f"::warning title=index version changed::{warning}")


def _append(path: Path | None, text: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


REQUIRED_BASELINE_KEYS = ("index_version", "index_documents", "index_chunks", "gold_sha256")


def _load_baseline(path: Path) -> dict[str, Any] | None:
    baseline = _load(path, "baseline")
    if baseline is None:
        return None
    missing = [key for key in REQUIRED_BASELINE_KEYS if key not in baseline]
    if missing:
        print(
            f"error: baseline {path} lacks {', '.join(missing)}; it was written by an older "
            "version. Regenerate it with `uv run python -m outage_matcher.evals.summary`.",
            file=sys.stderr,
        )
        return None
    return baseline


def _load(path: Path, what: str) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {what} {path}: {exc}", file=sys.stderr)
        return None


def gold_rows_in_index(
    conn: Any, chunk_ids: set[int], doc_ids: set[int]
) -> tuple[dict[int, ChunkRow], set[int]]:
    """What the index holds for the gold's chunk ids (document, URL, position) and doc ids."""
    chunks = conn.execute(
        "SELECT c.id, c.postmortem_id, p.url, c.ord FROM chunks c "
        "JOIN postmortems p ON p.id = c.postmortem_id WHERE c.id = ANY(%s)",
        (sorted(chunk_ids),),
    )
    docs = conn.execute("SELECT id FROM postmortems WHERE id = ANY(%s)", (sorted(doc_ids),))
    rows = {row[0]: ChunkRow(row[1], row[2], row[3]) for row in chunks.fetchall()}
    return rows, {row[0] for row in docs.fetchall()}


def cmd_index(args: argparse.Namespace) -> int:
    baseline = _load_baseline(args.baseline)
    if baseline is None:
        return 2
    gold = read_gold(args.gold)
    with db.connect() as conn:
        info = corpus_mod.index_info(conn)
        present = gold_rows_in_index(conn, *gold_ids(gold))
    problems = structural_problems(gold, *present, info.documents, info.chunks, baseline)
    if problems:
        message = _structural_error(problems)
        print(f"FAIL: {message}", file=sys.stderr)
        _append(args.summary_file, f"FAIL: {message}")
        return 1
    warning = version_warning(info.version, baseline)
    if warning:
        print(f"WARNING: {warning}")
        _append(args.summary_file, f"WARNING: {warning}")
        _annotate_warnings([warning])
    print(
        f"index {info.version} is compatible with the gold set "
        f"({info.documents} documents, {info.chunks} chunks)"
    )
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    baseline = _load_baseline(args.baseline)
    result = _load(args.result, "result")
    if baseline is None or result is None:
        return 2
    outcome = compare(result, baseline)
    text = render(outcome, baseline["tolerance"], baseline["run"])
    print(text)
    _append(args.summary_file, text)
    _annotate_warnings(outcome.warnings)
    return 0 if outcome.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gate", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in (
        ("index", cmd_index, "fail if the index cannot be scored with the gold set"),
        ("compare", cmd_compare, "fail when a result is worse than the baseline allows"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--baseline", type=Path, default=BASELINE_PATH)
        cmd.add_argument(
            "--summary-file", type=Path, help="also append the report here ($GITHUB_STEP_SUMMARY)"
        )
        cmd.set_defaults(func=func)
        if name == "index":
            cmd.add_argument("--gold", type=Path, default=GOLD_PATH)
        if name == "compare":
            cmd.add_argument(
                "result", type=Path, help="evals/results-style JSON from run_retrieval"
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, psycopg.Error) as exc:  # no DATABASE_URL, empty index, db down
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
