"""Regression gate for the retrieval eval, the same check CI runs (`.github/workflows/eval.yml`).

    uv run python -m outage_matcher.evals.gate index           # is the index the baseline's?
    uv run python -m outage_matcher.evals.gate compare RESULT  # did recall@k or MRR drop?

`evals/baseline.json` stores the baseline metrics, the index version and gold set they were
measured on, and a tolerance. Scores are only comparable on the same index and gold set, so:

- if the freshly built index version differs from the baseline's (the corpus drifted, or some
  pages could not be fetched), the gate fails and says to refresh the baseline;
- on the same index, it fails when any metric is below its baseline value minus the tolerance.

Exit code 0: pass; 1: fail; 2: a file is missing or unreadable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from outage_matcher import db
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals.summary import BASELINE_PATH, METRIC_KEYS

EPSILON = 1e-9  # a score exactly at the floor passes; this absorbs float rounding

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
    errors: list[str]  # why the gate cannot compare (index, gold or configuration differ)
    checks: list[MetricCheck]

    @property
    def passed(self) -> bool:
        return not self.errors and all(c.passed for c in self.checks)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def index_mismatch(version: str, baseline: dict[str, Any]) -> str | None:
    """A failure message when the index is not the one the baseline was recorded on."""
    if version == baseline["index_version"]:
        return None
    return (
        f"index version {version} differs from the baseline's {baseline['index_version']} "
        "(the corpus changed, or some pages could not be fetched). "
        "Scores on a different index are not comparable, so this fails instead of passing. "
        + REFRESH_HELP
    )


def compare(result: dict[str, Any], baseline: dict[str, Any]) -> GateResult:
    """Check one retrieval result file against the baseline."""
    errors: list[str] = []
    message = index_mismatch(result["index"]["version"], baseline)
    if message:
        errors.append(message)
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
    return GateResult(errors, checks)


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
    if result.errors:
        lines += [f"FAIL: {e}" for e in result.errors]
    elif not result.passed:
        names = ", ".join(c.name for c in result.checks if not c.passed)
        lines.append(f"FAIL: {names} dropped more than {tolerance} below the baseline.")
    else:
        lines.append("PASS: no metric dropped more than the tolerance.")
    return "\n".join(lines)


def _append(path: Path | None, text: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def _load(path: Path, what: str) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {what} {path}: {exc}", file=sys.stderr)
        return None


def cmd_index(args: argparse.Namespace) -> int:
    baseline = _load(args.baseline, "baseline")
    if baseline is None:
        return 2
    with db.connect() as conn:
        info = corpus_mod.index_info(conn)
    message = index_mismatch(info.version, baseline)
    if message:
        print(f"FAIL: {message}", file=sys.stderr)
        _append(args.summary_file, f"FAIL: {message}")
        return 1
    print(
        f"index {info.version} matches the baseline ({info.documents} documents, "
        f"{info.chunks} chunks)"
    )
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    baseline = _load(args.baseline, "baseline")
    result = _load(args.result, "result")
    if baseline is None or result is None:
        return 2
    outcome = compare(result, baseline)
    text = render(outcome, baseline["tolerance"], baseline["run"])
    print(text)
    _append(args.summary_file, text)
    return 0 if outcome.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gate", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in (
        ("index", cmd_index, "fail unless the loaded index is the baseline's"),
        ("compare", cmd_compare, "fail when a result is worse than the baseline allows"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--baseline", type=Path, default=BASELINE_PATH)
        cmd.add_argument(
            "--summary-file", type=Path, help="also append the report here ($GITHUB_STEP_SUMMARY)"
        )
        cmd.set_defaults(func=func)
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
