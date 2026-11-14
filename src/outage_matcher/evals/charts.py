"""Draw the README result figures from the recorded result files.

    uv run python -m outage_matcher.evals.charts [--results-dir DIR] [--out-dir DIR]

Every plotted value is a field of a file in `evals/results/`, read through the loaders in
`summary.py`; nothing is measured or typed in here. All figures are built before any is saved, so a
failed check writes nothing. matplotlib is a dev dependency and only this module imports it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from matplotlib.axes import Axes
from matplotlib.figure import Figure

from outage_matcher.evals.run_retrieval import RESULTS_DIR
from outage_matcher.evals.summary import (
    EARLIER_FAITHFULNESS_FILES,
    METRIC_KEYS,
    Run,
    check_comparable,
    config_label,
    load_earlier_faithfulness,
    load_runs,
    pick_baseline,
)

IMG_DIR = Path("docs/img")
DPI = 150
RANK_CAP = 10
RETRIEVAL_FILE = "retrieval-metrics.png"
FAITHFULNESS_PNG = "faithfulness-before-after.png"
RANK_FILE = "rank-change-rerank.png"

# Okabe-Ito colorblind-safe palette.
PALETTE = (
    "#000000",
    "#e69f00",
    "#56b4e9",
    "#009e73",
    "#f0e442",
    "#0072b2",
    "#d55e00",
    "#cc79a7",
)
BLUE, ORANGE, GREEN, VERMILLION = "#0072b2", "#e69f00", "#009e73", "#d55e00"
RUN_COLORS = (BLUE, ORANGE, GREEN, VERMILLION)
GRAY = "gray"
# Run names of the summary table, oldest first; sliced like `summary._render_earlier` does.
EARLIER_NAMES = ("before the fix, first run", "before the fix, second run")
NOW_NAME = "after the fix"


def binned_rank(rank: int | None, cap: int = RANK_CAP) -> int:
    """The rank if it is at most `cap`, else `cap + 1` (the shared "not in top 10" bin)."""
    return rank if rank is not None and rank <= cap else cap + 1


def _new_figure(size: tuple[float, float]) -> Figure:
    return Figure(figsize=size, layout="constrained", facecolor="white")


def _style(ax: Axes) -> None:
    ax.set_facecolor("white")
    ax.grid(axis="y", color="lightgray", linewidth=0.6)
    ax.set_axisbelow(True)


def _legend_below(ax: Axes, ncol: int = 1, offset: float = 0.12) -> None:
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -offset), ncol=ncol, frameon=False)


def _title(n: int) -> str:
    return f"n={n} synthetic queries"


def retrieval_figure(runs: list[Run]) -> Figure:
    """Grouped bars: one group per metric, one bar per retrieval run."""
    plain = [r for r in runs if r.config["chunking"] == "section" and not r.config["reranker"]]
    ordered = plain + [r for r in runs if r not in plain]
    n = runs[0].data["gold"]["queries"]
    fig = _new_figure((8, 5.5))
    ax = fig.add_subplot()
    _style(ax)
    width = 0.8 / len(ordered)
    for i, run in enumerate(ordered):
        xs = [g + (i - (len(ordered) - 1) / 2) * width for g in range(len(METRIC_KEYS))]
        heights = [run.metrics[key] for key in METRIC_KEYS]
        ax.bar(
            xs,
            heights,
            width=width,
            color=RUN_COLORS[i % len(RUN_COLORS)],
            edgecolor="none",
            label=config_label(run),
        )
    ax.set_xticks(range(len(METRIC_KEYS)), ["MRR" if k == "mrr" else k for k in METRIC_KEYS])
    ax.set_ylim(0, 1)
    ax.set_xlabel("metric")
    ax.set_ylabel("score (recall is a fraction of queries)")
    ax.set_title(f"Retrieval metrics by configuration, {_title(n)}")
    _legend_below(ax)
    return fig


def faithfulness_figure(earlier: Sequence[dict[str, Any]], now: dict[str, Any]) -> Figure:
    """Two panels over the same runs: judged and abstained counts, and the claim support rate."""
    runs = [*earlier, now]
    names = [*EARLIER_NAMES[-len(earlier) :], NOW_NAME] if earlier else [NOW_NAME]
    labels = [name.replace(", ", ",\n", 1) for name in names]
    n = now["gold"]["queries"]
    xs = list(range(len(runs)))
    fig = _new_figure((9, 5.5))
    counts, rates = fig.subplots(1, 2, sharex=True)
    for ax in (counts, rates):
        _style(ax)
    segments = [
        ("answers judged", "answered_and_judged", BLUE),
        ("abstained", "no_match", ORANGE),
    ]
    if any(d["metrics"]["errors"] > 0 for d in runs):
        segments.append(("errors", "errors", VERMILLION))
    bottoms = [0] * len(runs)
    for label, key, color in segments:
        values = [d["metrics"][key] for d in runs]
        counts.bar(
            xs, values, bottom=bottoms, width=0.6, color=color, edgecolor="none", label=label
        )
        bottoms = [b + v for b, v in zip(bottoms, values, strict=True)]
    counts.set_ylim(0, n)
    counts.set_ylabel("gold queries")
    counts.set_xlabel("faithfulness run")
    counts.set_title("Answers and abstentions")
    _legend_below(counts, ncol=len(segments), offset=0.2)
    present = [(x, d["metrics"]["claim_support_rate"]) for x, d in zip(xs, runs, strict=True)]
    present = [(x, rate) for x, rate in present if rate is not None]
    rates.bar([x for x, _ in present], [r for _, r in present], width=0.6, color=GREEN)
    rates.set_ylim(0, 1)
    rates.set_ylabel("claim support rate (judged answers only)")
    rates.set_xlabel("faithfulness run")
    rates.set_title("Claim support rate")
    counts.set_xticks(xs, labels)
    fig.suptitle(
        "Faithfulness before and after the citation-prompt fix\n"
        f"{_title(n)}, each bar a single nondeterministic run"
    )
    return fig


def rank_change_figure(base: Run, other: Run) -> Figure:
    """Paired dot plot: source-document rank per gold query, baseline against `other`."""
    n = base.data["gold"]["queries"]
    rows = sorted((binned_rank(base.ranks[q]), binned_rank(other.ranks[q]), q) for q in base.ranks)
    ys = list(range(len(rows)))
    before = [r[0] for r in rows]
    after = [r[1] for r in rows]
    fig = _new_figure((7, 9))
    ax = fig.add_subplot()
    _style(ax)
    ax.grid(axis="x", color="lightgray", linewidth=0.6)
    differ = [(y, b, a) for y, b, a in zip(ys, before, after, strict=True) if b != a]
    ax.hlines(
        [y for y, _, _ in differ],
        [min(b, a) for _, b, a in differ],
        [max(b, a) for _, b, a in differ],
        color=GRAY,
        linewidth=0.8,
        zorder=1,
    )
    ax.scatter(before, ys, s=55, marker="o", color=BLUE, label=config_label(base), zorder=2)
    ax.scatter(after, ys, s=40, marker="D", color=VERMILLION, label=config_label(other), zorder=3)
    ax.set_xticks(
        range(1, RANK_CAP + 2), [*map(str, range(1, RANK_CAP + 1)), f"not in top {RANK_CAP}"]
    )
    ax.tick_params(axis="x", labelsize=8)
    ax.set_yticks(ys, [r[2] for r in rows])
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlim(0.5, RANK_CAP + 1.9)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xlabel("rank of the source document")
    ax.set_ylabel("gold query")
    ax.set_title(f"Rank of the source document per query, {_title(n)}")
    _legend_below(ax, offset=0.06)
    return fig


def build_figures(results_dir: Path) -> dict[str, Figure]:
    """Load the result files, check them, and draw all three figures. Raises ValueError."""
    runs, faithfulness = load_runs(results_dir)
    earlier = load_earlier_faithfulness(results_dir)
    check_comparable(runs, faithfulness, earlier)
    baseline = pick_baseline(runs)
    if faithfulness is None:
        raise ValueError(f"no faithfulness.json in {results_dir}")
    if not earlier:
        raise ValueError(
            f"none of the earlier faithfulness files ({', '.join(EARLIER_FAITHFULNESS_FILES)}) "
            f"in {results_dir}"
        )
    cfg = baseline.config
    reranked = [
        r
        for r in runs
        if r.config["reranker"]
        and r.config["embedding_model"] == cfg["embedding_model"]
        and r.config["chunking"] == cfg["chunking"]
    ]
    if len(reranked) != 1:
        raise ValueError(
            f"expected exactly one reranked run of {config_label(baseline)}, found {len(reranked)}"
        )
    if baseline.ranks.keys() != reranked[0].ranks.keys():
        raise ValueError("the baseline and the reranked run cover different queries")
    for d in (*earlier, faithfulness):
        if d["metrics"]["queries"] != d["gold"]["queries"]:
            raise ValueError(
                f"a faithfulness run scored {d['metrics']['queries']} of "
                f"{d['gold']['queries']} gold queries (a --limit run); rerun it in full"
            )
    return {
        RETRIEVAL_FILE: retrieval_figure(runs),
        FAITHFULNESS_PNG: faithfulness_figure(earlier, faithfulness),
        RANK_FILE: rank_change_figure(baseline, reranked[0]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="charts", description=__doc__.split("\n\n")[0])
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=IMG_DIR)
    args = parser.parse_args(argv)
    try:
        figures = build_figures(args.results_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.out_dir / name for name in figures]
    for path, fig in zip(paths, figures.values(), strict=True):
        fig.savefig(path, dpi=DPI)
    print("wrote " + ", ".join(str(p) for p in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
