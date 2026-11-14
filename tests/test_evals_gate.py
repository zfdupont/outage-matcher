import copy
import json
from pathlib import Path

import psycopg
import pytest

from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals import gate
from outage_matcher.evals.gold import GoldQuery

ROOT = Path(__file__).resolve().parent.parent
BASELINE = json.loads((ROOT / "evals" / "baseline.json").read_text())
RECORDED = json.loads((ROOT / "evals" / "results" / "bge-section.json").read_text())


def make_baseline() -> dict:
    return {
        "run": "bge-section",
        "config": {"embedding_model": "bge", "chunking": "section", "reranker": None},
        "gold_sha256": "g" * 64,
        "index_version": "idx1",
        "index_documents": 200,
        "index_chunks": 1000,
        "metrics": {
            "recall@1": 0.4,
            "recall@3": 0.6,
            "recall@5": 0.7,
            "recall@10": 0.8,
            "mrr": 0.5,
        },
        "tolerance": 0.05,
    }


def make_result(version="idx1", documents=200, chunks=1000, **metric_overrides) -> dict:
    baseline = make_baseline()
    return {
        "index": {"version": version, "documents": documents, "chunks": chunks},
        "gold": {"sha256": baseline["gold_sha256"]},
        "config": copy.deepcopy(baseline["config"]),
        "metrics": {**baseline["metrics"], **metric_overrides},
    }


def make_gold(*rows) -> list[GoldQuery]:
    """rows: (doc_id, held_out_chunk_ids, confirmed near-duplicate doc ids)"""
    from outage_matcher.evals.gold import gold_from_json

    out = []
    for n, (doc_id, chunk_ids, near) in enumerate(rows):
        out.append(
            gold_from_json(
                {
                    "id": f"q{n:03d}",
                    "query": "q",
                    "doc_id": doc_id,
                    "doc_url": "u",
                    "doc_title": "t",
                    "source": "s",
                    "held_out_chunk_id": chunk_ids[0],
                    "held_out_chunk_ids": chunk_ids,
                    "held_out_ords": [0],
                    "held_out_heading": "h",
                    "index_version": "idx0",
                    "generation": {},
                    "notes": "",
                    "near_duplicates": [
                        {
                            "doc_id": d,
                            "title": "t",
                            "url": "u",
                            "reason": "r",
                            "confirmed": True,
                        }
                        for d in near
                    ]
                    + [{"doc_id": 999, "title": "t", "url": "u", "reason": "r"}],  # unconfirmed
                }
            )
        )
    return out


GOLD = make_gold((1, [10, 11], []), (2, [20], [3]))


# ----- the rule: version, metrics -------------------------------------------------------------


def test_same_version_and_metrics_pass_without_warning():
    outcome = gate.compare(make_result(), make_baseline())
    assert outcome.passed and outcome.errors == [] and outcome.warnings == []
    assert [c.name for c in outcome.checks] == [
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@10",
        "mrr",
    ]
    assert "PASS" in gate.render(outcome, 0.05, "bge-section")
    assert "WARNING" not in gate.render(outcome, 0.05, "bge-section")


def test_version_differs_but_metrics_equal_passes_with_a_warning_naming_both_versions():
    outcome = gate.compare(make_result(version="idx2"), make_baseline())
    assert outcome.passed and outcome.errors == []
    assert len(outcome.warnings) == 1
    assert "idx2" in outcome.warnings[0] and "idx1" in outcome.warnings[0]
    text = gate.render(outcome, 0.05, "bge-section")
    assert "WARNING: index version idx2 differs from the baseline's idx1" in text
    assert "PASS" in text and "FAIL" not in text


def test_version_differs_and_metrics_regress_fails_and_still_warns():
    outcome = gate.compare(make_result(version="idx2", mrr=0.3), make_baseline())
    assert not outcome.passed and outcome.errors == []
    assert [c.name for c in outcome.checks if not c.passed] == ["mrr"]
    text = gate.render(outcome, 0.05, "bge-section")
    assert "WARNING" in text and "FAIL: mrr dropped" in text and "REGRESSED" in text


def test_improvement_passes():
    assert gate.compare(make_result(mrr=0.9, **{"recall@5": 0.95}), make_baseline()).passed


def test_drop_within_tolerance_passes_and_exactly_at_the_floor_passes():
    # 0.7 - 0.05 = 0.6499999999999999 in floats; a score of 0.65 sits on the floor.
    assert gate.compare(make_result(**{"recall@5": 0.65}), make_baseline()).passed
    assert gate.compare(make_result(mrr=0.46), make_baseline()).passed


@pytest.mark.parametrize("metric", ["recall@1", "recall@3", "recall@5", "recall@10", "mrr"])
def test_drop_beyond_tolerance_fails_naming_the_metric(metric):
    baseline = make_baseline()
    outcome = gate.compare(make_result(**{metric: baseline["metrics"][metric] - 0.0501}), baseline)
    assert not outcome.passed
    assert [c.name for c in outcome.checks if not c.passed] == [metric]
    text = gate.render(outcome, baseline["tolerance"], baseline["run"])
    assert "REGRESSED" in text and f"FAIL: {metric} dropped" in text


# ----- the rule: structural incompatibility ---------------------------------------------------


def test_count_drift_up_to_two_percent_is_comparable():
    assert gate.count_drift(204, 1020, make_baseline()) == []  # exactly 2 percent each
    assert gate.count_drift(196, 980, make_baseline()) == []
    assert gate.compare(make_result(documents=204, chunks=980), make_baseline()).passed


def test_count_drift_beyond_two_percent_is_a_hard_failure_with_refresh_instructions():
    outcome = gate.compare(make_result(documents=205), make_baseline())
    assert not outcome.passed
    message = outcome.errors[0]
    assert "205 documents but the baseline's has 200" in message
    assert "refresh the baseline" in message and "evals/baseline.json" in message
    outcome = gate.compare(make_result(chunks=900), make_baseline())
    assert "900 chunks but the baseline's has 1000" in outcome.errors[0]


def test_missing_gold_chunk_id_is_a_hard_failure_naming_the_id():
    problems = gate.structural_problems(GOLD, {10, 20}, {1, 2, 3}, 200, 1000, make_baseline())
    assert len(problems) == 1
    assert "held-out chunk ids missing" in problems[0] and "11" in problems[0]


def test_missing_relevant_doc_id_is_a_hard_failure_but_unconfirmed_duplicates_do_not_count():
    # doc 3 is a confirmed near-duplicate of query 2, doc 999 is unconfirmed.
    problems = gate.structural_problems(GOLD, {10, 11, 20}, {1, 2}, 200, 1000, make_baseline())
    assert len(problems) == 1
    assert "relevant document ids missing" in problems[0] and "3" in problems[0]
    assert "999" not in problems[0]


def test_compatible_index_has_no_structural_problems():
    ok = gate.structural_problems(GOLD, {10, 11, 20, 30}, {1, 2, 3, 4}, 200, 1000, make_baseline())
    assert ok == []


def test_structural_problems_are_all_reported_together():
    problems = gate.structural_problems(GOLD, set(), set(), 100, 500, make_baseline())
    assert len(problems) == 4


def test_a_different_gold_set_or_configuration_fails():
    result = make_result()
    result["gold"]["sha256"] = "h" * 64
    result["config"]["chunking"] = "neighbor"
    outcome = gate.compare(result, make_baseline())
    assert not outcome.passed
    assert any("gold set differs" in e for e in outcome.errors)
    assert any("chunking" in e and "neighbor" in e for e in outcome.errors)


def test_version_warning_helper():
    assert gate.version_warning("idx1", make_baseline()) is None
    assert "idx9" in gate.version_warning("idx9", make_baseline())


def test_the_committed_baseline_passes_against_its_own_recorded_run():
    outcome = gate.compare(RECORDED, BASELINE)
    assert outcome.passed, outcome.errors
    assert outcome.warnings == []
    assert BASELINE["index_version"] == RECORDED["index"]["version"]
    assert (BASELINE["index_documents"], BASELINE["index_chunks"]) == (
        RECORDED["index"]["documents"],
        RECORDED["index"]["chunks"],
    )


def test_the_committed_baseline_fails_on_a_drop_beyond_its_tolerance():
    worse = copy.deepcopy(RECORDED)
    worse["metrics"]["recall@3"] -= 0.06  # more than the 0.05 tolerance
    assert not gate.compare(worse, BASELINE).passed


# ----- command line --------------------------------------------------------------------------


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_compare_command_exit_codes_and_summary_file(tmp_path, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    good = write(tmp_path, "good.json", make_result())
    drifted = write(tmp_path, "drifted.json", make_result(version="idx2"))
    bad = write(tmp_path, "bad.json", make_result(mrr=0.1))
    summary = tmp_path / "summary.md"
    argv = ["compare", "--baseline", str(baseline), "--summary-file", str(summary)]

    assert gate.main([*argv, str(good)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert gate.main([*argv, str(drifted)]) == 0  # a new version alone does not fail
    assert "WARNING: index version idx2 differs from the baseline's idx1" in capsys.readouterr().out
    assert gate.main([*argv, str(bad)]) == 1
    assert "FAIL: mrr dropped" in capsys.readouterr().out
    report = summary.read_text()
    assert report.count("| metric |") == 3 and "WARNING" in report and "FAIL" in report


def test_compare_command_emits_a_github_annotation_only_on_actions(tmp_path, monkeypatch, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    drifted = write(tmp_path, "drifted.json", make_result(version="idx2"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    gate.main(["compare", "--baseline", str(baseline), str(drifted)])
    assert "::warning" not in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    gate.main(["compare", "--baseline", str(baseline), str(drifted)])
    assert "::warning title=index version changed::index version idx2" in capsys.readouterr().out


def test_compare_command_missing_file_is_exit_2(tmp_path, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    assert gate.main(["compare", "--baseline", str(baseline), str(tmp_path / "nope.json")]) == 2
    assert "cannot read result" in capsys.readouterr().err


class FakeDb:
    """Stands in for `db.connect()` and holds the ids the index contains."""

    def __init__(self, chunk_ids, doc_ids):
        self.chunk_ids, self.doc_ids = set(chunk_ids), set(doc_ids)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.queries.append(sql)
        wanted = set(params[0])
        pool = self.chunk_ids if "FROM chunks" in sql else self.doc_ids
        rows = [(i,) for i in sorted(wanted & pool)]
        return type("Rows", (), {"fetchall": lambda self_: rows})()


def index_command(tmp_path, monkeypatch, db, version="idx1", documents=200, chunks=1000):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    gold = tmp_path / "gold.jsonl"
    from dataclasses import asdict

    gold.write_text("".join(json.dumps(asdict(g)) + "\n" for g in GOLD))
    monkeypatch.setattr(gate.db, "connect", lambda: db)
    monkeypatch.setattr(
        corpus_mod, "index_info", lambda conn: corpus_mod.IndexInfo(version, documents, chunks)
    )
    summary = tmp_path / "summary.md"
    argv = ["index", "--baseline", str(baseline), "--gold", str(gold)]
    return [*argv, "--summary-file", str(summary)], summary


def test_present_ids_queries_chunks_and_documents():
    db = FakeDb({10, 11}, {1, 2})
    assert gate.present_ids(db, {10, 99}, {2, 98}) == ({10}, {2})
    assert len(db.queries) == 2


def test_index_command_passes_silently_on_the_baseline_version(tmp_path, monkeypatch, capsys):
    argv, _ = index_command(tmp_path, monkeypatch, FakeDb({10, 11, 20}, {1, 2, 3}))
    assert gate.main(argv) == 0
    out = capsys.readouterr().out
    assert "compatible with the gold set" in out and "WARNING" not in out


def test_index_command_warns_but_passes_on_another_version(tmp_path, monkeypatch, capsys):
    argv, summary = index_command(
        tmp_path, monkeypatch, FakeDb({10, 11, 20}, {1, 2, 3}), version="idx9"
    )
    assert gate.main(argv) == 0
    out = capsys.readouterr().out
    assert "WARNING: index version idx9 differs from the baseline's idx1" in out
    assert "WARNING" in summary.read_text()


def test_index_command_fails_on_a_missing_gold_chunk(tmp_path, monkeypatch, capsys):
    argv, summary = index_command(tmp_path, monkeypatch, FakeDb({10, 20}, {1, 2, 3}))
    assert gate.main(argv) == 1
    err = capsys.readouterr().err
    assert "FAIL" in err and "chunk ids missing" in err and "refresh the baseline" in err
    assert "refresh the baseline" in summary.read_text()


def test_index_command_fails_on_count_drift(tmp_path, monkeypatch, capsys):
    argv, _ = index_command(tmp_path, monkeypatch, FakeDb({10, 11, 20}, {1, 2, 3}), documents=150)
    assert gate.main(argv) == 1
    assert "150 documents but the baseline's has 200" in capsys.readouterr().err


def test_index_command_database_down_is_exit_2(tmp_path, monkeypatch, capsys):
    argv, _ = index_command(tmp_path, monkeypatch, FakeDb(set(), set()))

    def refuse():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(gate.db, "connect", refuse)
    assert gate.main(argv) == 2
    assert "connection refused" in capsys.readouterr().err
