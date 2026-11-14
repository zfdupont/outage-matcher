import json

import pytest

from outage_matcher.evals import metrics, summary


def run_file(name, model, ranks, chunking="section", reranker=None, gold="g1", index="i1"):
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
        "index": {"version": index, "documents": 3, "chunks": 9},
        "gold": {
            "path": "evals/gold.jsonl",
            "sha256": gold * 12,
            "queries": len(ranks),
            "generation": {"model": "deepseek-flash", "date": "2026-11-13"},
        },
        "metrics": metrics.compute_metrics(ranks),
        "per_query": [{"id": f"q{i}", "rank": r} for i, r in enumerate(ranks)],
    }


def write(dir_, *docs):
    for doc in docs:
        (dir_ / f"{doc['run']}.json").write_text(json.dumps(doc))


FAITHFULNESS = {
    "run": "faithfulness",
    "date": "2026-11-14",
    "gold": {"sha256": "g1" * 12},
    "index": {"version": "i1"},
    "config": {
        "agent_model": "claude-x",
        "judge_model": "deepseek-flash",
        "judge_temperature": 0.0,
    },
    "metrics": {
        "queries": 4,
        "answered_and_judged": 3,
        "no_match": 1,
        "errors": 0,
        "claims": 8,
        "claims_supported": 6,
        "claim_support_rate": 0.75,
        "faithful_answer_rate": 2 / 3,
    },
    "tokens": {
        "agent": {"input_tokens": 1000, "output_tokens": 100, "calls": 9},
        "judge": {"input_tokens": 500, "output_tokens": 50, "calls": 3},
    },
}


@pytest.fixture
def results(tmp_path):
    write(
        tmp_path,
        run_file("bge-section", "bge", [1, 2, 4, None]),
        run_file("minilm-section", "minilm", [2, 3, 5, None]),
        run_file("bge-section-rerank-x", "bge", [1, 1, 2, 3], reranker="org/x"),
    )
    (tmp_path / "faithfulness.json").write_text(json.dumps(FAITHFULNESS))
    return tmp_path


def test_baseline_is_the_better_model_under_section_chunking(results):
    runs, _ = summary.load_runs(results)
    assert summary.pick_baseline(runs).name == "bge-section"


def test_compare_ranks_counts_better_worse_and_same_queries(results):
    runs, _ = summary.load_runs(results)
    by_name = {r.name: r for r in runs}
    base, improved = by_name["bge-section"], by_name["bge-section-rerank-x"]
    # ranks 1,2,4,None against 1,1,2,3
    assert summary.compare_ranks(base, improved) == (3, 0, 1)
    assert summary.compare_ranks(improved, base) == (0, 3, 1)


def test_summary_tables_copy_the_recorded_numbers(results):
    runs, faithfulness = summary.load_runs(results)
    text = summary.render_summary(runs, faithfulness)
    assert "| bge (org/bge) | 0.250 | 0.500 | 0.750 | 0.750 | 0.438 |" in text
    assert "| minilm (org/minilm) | 0.000 | 0.500 | 0.750 | 0.750 | 0.258 |" in text
    assert "rerank org/x (top 50)" in text and "+0.271" in text and "3 / 0 / 1" in text
    assert "Baseline: **bge, section chunking**" in text
    assert "6 of 8" in text and "0.750" in text and "0.667" in text
    assert "deepseek-flash (DeepSeek, a different model family)" in text
    assert "synthetic" in text


def test_summary_without_faithfulness_omits_that_section(tmp_path):
    write(tmp_path, run_file("bge-section", "bge", [1, 2]))
    runs, faithfulness = summary.load_runs(tmp_path)
    assert faithfulness is None
    assert "Faithfulness" not in summary.render_summary(runs, faithfulness)


def test_runs_on_different_gold_sets_or_indexes_are_not_compared(tmp_path):
    write(tmp_path, run_file("a", "bge", [1]), run_file("b", "minilm", [1], gold="g2"))
    runs, _ = summary.load_runs(tmp_path)
    with pytest.raises(ValueError, match="differ in gold set"):
        summary.render_summary(runs, None)
    write(tmp_path, run_file("b", "minilm", [1], index="i2"))
    with pytest.raises(ValueError, match="index"):
        summary.render_summary(*summary.load_runs(tmp_path))


def test_baseline_document_states_the_tolerance_and_ties_to_gold_and_index(results):
    runs, _ = summary.load_runs(results)
    doc = summary.baseline_document(summary.pick_baseline(runs), 0.05)
    assert doc["run"] == "bge-section" and doc["tolerance"] == 0.05
    assert doc["metrics"]["recall@1"] == 0.25 and set(doc["metrics"]) == set(summary.METRIC_KEYS)
    assert doc["gold_sha256"] == "g1" * 12 and doc["index_version"] == "i1"


def test_main_writes_summary_and_baseline(results, tmp_path):
    out, baseline = tmp_path / "out" / "summary.md", tmp_path / "out" / "baseline.json"
    argv = [
        "--results-dir",
        str(results),
        "--out",
        str(results / "summary.md"),
        "--baseline-out",
        str(baseline),
    ]
    out.parent.mkdir()
    assert summary.main(argv) == 0
    assert (results / "summary.md").read_text().startswith("# Eval results")
    assert json.loads(baseline.read_text())["tolerance"] == summary.DEFAULT_TOLERANCE
    # the generated summary is not mistaken for a result file on a second run
    assert summary.main(argv) == 0


def test_main_with_no_results_reports_an_error(tmp_path, capsys):
    assert summary.main(["--results-dir", str(tmp_path), "--out", str(tmp_path / "s.md")]) == 1
    assert "baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    "changes",
    [{"gold": {"sha256": "other" * 4}}, {"index": {"version": "i2"}}],
    ids=["gold", "index"],
)
def test_a_faithfulness_result_from_another_gold_set_or_index_is_refused(results, changes, capsys):
    (results / "faithfulness.json").write_text(json.dumps({**FAITHFULNESS, **changes}))
    runs, faithfulness = summary.load_runs(results)
    with pytest.raises(ValueError, match="differ in gold set"):
        summary.render_summary(runs, faithfulness)
    out = results / "summary.md"
    argv = ["--results-dir", str(results), "--out", str(out), "--baseline-out", str(results / "b")]
    assert summary.main(argv) == 1
    assert "differ" in capsys.readouterr().err and not out.exists()
