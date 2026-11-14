import io
import json
import re
import tomllib
from pathlib import Path

import pytest
from matplotlib import colors as mcolors
from matplotlib.text import Text
from PIL import Image

from outage_matcher.evals import charts, metrics, summary

ROOT = Path(__file__).resolve().parent.parent
RECORDED = ROOT / "evals" / "results"
SUMMARY_MD = (RECORDED / "summary.md").read_text(encoding="utf-8")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FILE_NAMES = {charts.RETRIEVAL_FILE, charts.FAITHFULNESS_PNG, charts.RANK_FILE}
IMAGES = ["retrieval-metrics.png", "faithfulness-before-after.png", "rank-change-rerank.png"]


def table_rows(heading: str) -> list[list[str]]:
    """Body rows of the first markdown table after `heading` in the committed summary.md."""
    lines = SUMMARY_MD.splitlines()
    start = lines.index(heading) + 1
    rows = []
    for line in lines[start:]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return rows[2:]  # header and separator


def recorded_runs():
    runs, faithfulness = summary.load_runs(RECORDED)
    return runs, faithfulness, summary.load_earlier_faithfulness(RECORDED)


def recorded_figures() -> dict:
    return charts.build_figures(RECORDED)


def find_run(runs, name):
    return next(r for r in runs if r.name == name)


def rendered(fig):
    """Save to memory so tick labels and the layout exist, then return the figure."""
    fig.savefig(io.BytesIO(), dpi=50)
    return fig


def all_titles(fig) -> list[str]:
    suptitle = [fig._suptitle.get_text()] if fig._suptitle is not None else []
    return suptitle + [ax.get_title() for ax in fig.axes]


def container_heights(container) -> list[float]:
    return [p.get_height() for p in container.patches]


# ---------- fixtures ----------


def run_file(name, model, ranks, chunking="section", reranker=None, gold="g1"):
    return {
        "run": name,
        "date": "2026-11-14",
        "config": {
            "embedding_model": model,
            "embedding_model_name": f"org/{model}",
            "chunking": chunking,
            "reranker": reranker,
            "rerank_depth": 50 if reranker else None,
        },
        "index": {"version": "i1", "documents": 3, "chunks": 9},
        "gold": {
            "path": "evals/gold.jsonl",
            "sha256": gold * 12,
            "queries": len(ranks),
            "generation": {"model": "deepseek-flash", "date": "2026-11-13"},
        },
        "metrics": metrics.compute_metrics(ranks),
        "per_query": [{"id": f"q{i}", "rank": r} for i, r in enumerate(ranks)],
    }


def faith_file(
    answered=3, no_match=1, errors=0, rate: float | None = 0.75, queries=4, gold_queries=4
):
    return {
        "date": "2026-11-14",
        "gold": {"sha256": "g1" * 12, "queries": gold_queries},
        "index": {"version": "i1"},
        "metrics": {
            "queries": queries,
            "answered_and_judged": answered,
            "no_match": no_match,
            "errors": errors,
            "claim_support_rate": rate,
        },
    }


def write_dir(
    dir_: Path,
    faithfulness: dict | None = None,
    earlier: list[dict] | None = None,
    runs: list[dict] | None = None,
) -> Path:
    runs = runs or [
        run_file("bge-section", "bge", [1, 2, 4, None]),
        run_file("minilm-section", "minilm", [2, 3, 5, None]),
        run_file("bge-section-rerank-x", "bge", [1, 1, 2, 3], reranker="org/x"),
        run_file("bge-neighbor", "bge", [1, 3, 4, None], chunking="neighbor"),
    ]
    for doc in runs:
        (dir_ / f"{doc['run']}.json").write_text(json.dumps(doc))
    if faithfulness is None:
        faithfulness = faith_file()
    (dir_ / "faithfulness.json").write_text(json.dumps(faithfulness))
    if earlier is None:
        earlier = [faith_file(answered=2, no_match=2, rate=0.5)]
    # one earlier run is the second pre-fix file
    names = summary.EARLIER_FAITHFULNESS_FILES[-len(earlier) :] if earlier else []
    for name, doc in zip(names, earlier, strict=True):
        (dir_ / name).write_text(json.dumps(doc))
    return dir_


def _make(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return write_dir(d)


@pytest.fixture
def fixture_dir(tmp_path):
    return _make(tmp_path)


# ---------- AC1 ----------


def test_main_writes_three_pngs(tmp_path, capsys):
    out = tmp_path / "img"
    code = charts.main(["--results-dir", str(RECORDED), "--out-dir", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert printed.startswith("wrote ")
    assert {p.name for p in out.iterdir()} == FILE_NAMES
    for path in out.iterdir():
        assert path.read_bytes().startswith(PNG_SIGNATURE)
        assert path.stat().st_size < 150 * 1024
        with Image.open(path) as image:
            assert round(image.info["dpi"][0]) == 150
            assert round(image.info["dpi"][1]) == 150
            assert image.convert("RGBA").getpixel((0, 0)) == (255, 255, 255, 255)


# ---------- AC2 ----------


def test_retrieval_bars_match_summary_table():
    runs, _, _ = recorded_runs()
    fig = charts.retrieval_figure(runs)
    containers = fig.axes[0].containers
    expected_order = [
        find_run(runs, "bge-section"),
        find_run(runs, "minilm-section"),
        find_run(runs, "bge-neighbor"),
        find_run(runs, "bge-section-rerank-ms-marco-minilm-l-6-v2"),
    ]
    assert [c.get_label() for c in containers] == [summary.config_label(r) for r in expected_order]
    table = {row[0]: row[1:6] for row in table_rows("## Improvements on the identical gold set")}
    for row in table_rows("## Embedding models (section chunking)"):
        table.setdefault(f"{row[0].split(' (')[0]}, section chunking", row[1:6])
    for container, run in zip(containers, expected_order, strict=True):
        assert len(container.patches) == 5
        assert [f"{h:.3f}" for h in container_heights(container)] == table[
            summary.config_label(run)
        ]
        assert container_heights(container) == [run.metrics[k] for k in summary.METRIC_KEYS]


# ---------- AC3 ----------


def test_fixture_bar_heights_and_titles(fixture_dir):
    figures = charts.build_figures(fixture_dir)
    assert set(figures) == FILE_NAMES
    runs, _ = summary.load_runs(fixture_dir)
    fig = figures[charts.RETRIEVAL_FILE]
    ordered = [
        find_run(runs, "bge-section"),
        find_run(runs, "minilm-section"),
        find_run(runs, "bge-neighbor"),
        find_run(runs, "bge-section-rerank-x"),
    ]
    for container, run in zip(fig.axes[0].containers, ordered, strict=True):
        assert container_heights(container) == [run.metrics[k] for k in summary.METRIC_KEYS]
    for fig in figures.values():
        assert any("n=4 synthetic queries" in t for t in all_titles(fig))
        assert not any("n=34" in t for t in all_titles(fig))


# ---------- AC4 ----------


def test_faithfulness_panels_match_summary_table():
    fig = recorded_figures()[charts.FAITHFULNESS_PNG]
    rendered(fig)
    counts, rates = fig.axes
    rows = table_rows("### Before and after the citation-prompt fix")
    assert len(rows) == 3
    labels = [t.get_text().replace("\n", " ") for t in counts.get_xticklabels()]
    assert labels == [re.sub(r" \(\d{4}-\d{2}-\d{2}\)$", "", row[0]) for row in rows]
    assert [t.get_text().replace("\n", " ") for t in rates.get_xticklabels()] == labels
    by_label = {c.get_label(): container_heights(c) for c in counts.containers}
    assert set(by_label) == {"answers judged", "abstained"}
    for i, row in enumerate(rows):
        judged, total = row[1].split(" of ")
        assert by_label["answers judged"][i] == int(judged)
        assert by_label["abstained"][i] == int(row[2])
        assert int(judged) + int(row[2]) == int(total)
    assert [f"{p.get_height():.3f}" for p in rates.patches] == [row[4] for row in rows]
    titles = " ".join(all_titles(fig))
    assert "n=34 synthetic queries" in titles
    assert "single nondeterministic run" in titles


# ---------- AC5 ----------


def test_errors_segment_only_when_a_run_has_errors(tmp_path):
    earlier = [faith_file(answered=2, no_match=1, errors=1, rate=0.5)]
    now = faith_file()
    fig = charts.faithfulness_figure(earlier, now)
    labels = [c.get_label() for c in fig.axes[0].containers]
    assert labels == ["answers judged", "abstained", "errors"]
    assert container_heights(fig.axes[0].containers[2]) == [1, 0]
    clean = charts.faithfulness_figure([faith_file()], faith_file())
    assert [c.get_label() for c in clean.axes[0].containers] == ["answers judged", "abstained"]


def test_null_claim_support_rate_gets_no_bar():
    earlier = [faith_file(answered=0, no_match=4, rate=None)]
    fig = charts.faithfulness_figure(earlier, faith_file(rate=0.75))
    rendered(fig)
    rates = fig.axes[1]
    assert [p.get_height() for p in rates.patches] == [0.75]
    assert [p.get_x() + p.get_width() / 2 for p in rates.patches] == [1]


# ---------- AC6 ----------


def test_binned_rank():
    assert [charts.binned_rank(r) for r in (1, 10, 11, 152, None)] == [1, 10, 11, 11, 11]


def test_rank_markers_match_recorded_ranks():
    runs, _, _ = recorded_runs()
    base = find_run(runs, "bge-section")
    other = find_run(runs, "bge-section-rerank-ms-marco-minilm-l-6-v2")
    fig = rendered(charts.rank_change_figure(base, other))
    ax = fig.axes[0]
    ids = {int(y): t.get_text() for y, t in zip(ax.get_yticks(), ax.get_yticklabels(), strict=True)}
    assert len(ids) == 34

    def positions(run):
        (coll,) = [c for c in ax.collections if c.get_label() == summary.config_label(run)]
        return {ids[round(y)]: x for x, y in coll.get_offsets()}

    got_base, got_other = positions(base), positions(other)
    assert set(got_base) == set(base.ranks) == set(got_other)
    for query_id, rank in base.ranks.items():
        assert got_base[query_id] == charts.binned_rank(rank)
        assert got_other[query_id] == charts.binned_rank(other.ranks[query_id])
    ticks = dict(zip(ax.get_xticks(), (t.get_text() for t in ax.get_xticklabels()), strict=True))
    assert ticks[11] == "not in top 10"
    assert ticks[1] == "1" and ticks[10] == "10"


def test_rank_rows_sorted_by_baseline_then_reranked_then_id():
    runs, _, _ = recorded_runs()
    base = find_run(runs, "bge-section")
    other = find_run(runs, "bge-section-rerank-ms-marco-minilm-l-6-v2")
    ax = charts.rank_change_figure(base, other).axes[0]
    keys = [
        (charts.binned_rank(base.ranks[q]), charts.binned_rank(other.ranks[q]), q)
        for q in (t.get_text() for t in _labels(ax))
    ]
    assert keys == sorted(keys)


def _labels(ax):
    return [t for _, t in sorted(zip(ax.get_yticks(), ax.get_yticklabels(), strict=True))]


# ---------- AC7 ----------


def bar_and_marker_colors(ax) -> set[str]:
    found = {mcolors.to_hex(p.get_facecolor()) for p in ax.patches}
    for coll in ax.collections:
        if coll.get_label() and not coll.get_label().startswith("_"):  # scatter series
            found |= {mcolors.to_hex(c) for c in coll.get_facecolors()}
    return found


@pytest.mark.parametrize("name", sorted(FILE_NAMES))
def test_style_rules(name):
    fig = rendered(recorded_figures()[name])
    assert mcolors.to_hex(fig.get_facecolor()) == "#ffffff"
    for ax in fig.axes:
        assert mcolors.to_hex(ax.get_facecolor()) == "#ffffff"
        assert ax.get_xlabel().strip() and ax.get_ylabel().strip()
        colors = bar_and_marker_colors(ax)
        assert colors and colors <= set(charts.PALETTE)
        legend = ax.get_legend()
        series = len(ax.containers) + len(
            [c for c in ax.collections if c.get_label() and not c.get_label().startswith("_")]
        )
        if series > 1:
            assert legend is not None
    for text in fig.findobj(Text):
        assert text.get_text().isascii(), text.get_text()


def test_y_limits_fixed_to_unit_interval():
    figures = recorded_figures()
    assert figures[charts.RETRIEVAL_FILE].axes[0].get_ylim() == (0, 1)
    assert figures[charts.FAITHFULNESS_PNG].axes[1].get_ylim() == (0, 1)


def test_no_numeric_annotations_on_bars():
    for fig in recorded_figures().values():
        for ax in fig.axes:
            assert len(ax.texts) == 0


# ---------- AC8 ----------


def run_error_case(tmp_path, capsys, mutate):
    results = _make(tmp_path)
    mutate(results)
    out = tmp_path / "img"
    code = charts.main(["--results-dir", str(results), "--out-dir", str(out)])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("error: ")
    assert not out.exists() or list(out.iterdir()) == []


def _rewrite(path: Path, fn):
    doc = json.loads(path.read_text())
    fn(doc)
    path.write_text(json.dumps(doc))


def _two_gold(results):
    _rewrite(results / "minilm-section.json", lambda d: d["gold"].update(sha256="x" * 24))


def _no_faithfulness(results):
    (results / "faithfulness.json").unlink()


def _no_earlier(results):
    for name in summary.EARLIER_FAITHFULNESS_FILES:
        (results / name).unlink(missing_ok=True)


def _no_reranked(results):
    (results / "bge-section-rerank-x.json").unlink()


def _two_reranked(results):
    doc = json.loads((results / "bge-section-rerank-x.json").read_text())
    doc["run"] = "bge-section-rerank-y"
    (results / "bge-section-rerank-y.json").write_text(json.dumps(doc))


def _limited_faithfulness(results):
    _rewrite(results / "faithfulness.json", lambda d: d["metrics"].update(queries=2))


def _limited_earlier(results):
    path = results / summary.EARLIER_FAITHFULNESS_FILES[-1]
    _rewrite(path, lambda d: d["metrics"].update(queries=2))


def _no_baseline(results):
    (results / "bge-section.json").unlink()
    (results / "minilm-section.json").unlink()


@pytest.mark.parametrize(
    "mutate",
    [
        _two_gold,
        _no_faithfulness,
        _no_earlier,
        _no_reranked,
        _two_reranked,
        _limited_faithfulness,
        _limited_earlier,
        _no_baseline,
    ],
)
def test_errors_exit_1_and_write_nothing(tmp_path, capsys, mutate):
    run_error_case(tmp_path, capsys, mutate)


# ---------- AC9 ----------

README = (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", IMAGES)
def test_committed_png_is_valid(name):
    path = ROOT / "docs" / "img" / name
    assert path.read_bytes().startswith(PNG_SIGNATURE)
    assert path.stat().st_size < 150 * 1024
    with Image.open(path) as image:
        image.verify()


@pytest.mark.parametrize("name", IMAGES)
def test_readme_links_each_image_with_a_figure_caption(name):
    lines = README.splitlines()
    links = [i for i, line in enumerate(lines) if f"(docs/img/{name})" in line]
    assert len(links) == 1
    assert lines[links[0]].startswith("![")
    following = [line for line in lines[links[0] + 1 :] if line.strip()]
    assert following[0].startswith("Figure:")


# ---------- AC10, AC11 ----------


def test_readme_keeps_every_summary_line():
    lines = SUMMARY_MD.splitlines()
    start = lines.index("## Embedding models (section chunking)")
    readme_lines = set(README.splitlines())
    for line in lines[start:]:
        if line.strip() and not line.startswith("#"):
            assert line in readme_lines, line


def test_summary_md_is_reproduced_byte_for_byte():
    runs, faithfulness, earlier = recorded_runs()
    assert summary.render_summary(runs, faithfulness, earlier) == SUMMARY_MD


# ---------- AC12, AC13 ----------


def test_matplotlib_is_a_dev_only_dependency():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = pyproject["dependency-groups"]["dev"]
    assert any(re.match(r"matplotlib\b", d) for d in dev)
    assert not any(re.match(r"matplotlib\b", d) for d in pyproject["project"]["dependencies"])
    requirements = (ROOT / "requirements-dev.txt").read_text().split()
    assert "matplotlib" in requirements


def test_only_charts_imports_matplotlib():
    for path in (ROOT / "src").rglob("*.py"):
        if path == ROOT / "src" / "outage_matcher" / "evals" / "charts.py":
            continue
        text = path.read_text()
        assert "import matplotlib" not in text and "from matplotlib" not in text, path


def test_command_is_documented():
    command = "uv run python -m outage_matcher.evals.charts"
    assert command in (ROOT / "CLAUDE.md").read_text()
    assert command in README
