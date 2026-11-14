import copy
import json
from pathlib import Path

import psycopg
import pytest

from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals import gate

ROOT = Path(__file__).resolve().parent.parent
BASELINE = json.loads((ROOT / "evals" / "baseline.json").read_text())
RECORDED = json.loads((ROOT / "evals" / "results" / "bge-section.json").read_text())


def make_baseline() -> dict:
    return {
        "run": "bge-section",
        "config": {"embedding_model": "bge", "chunking": "section", "reranker": None},
        "gold_sha256": "g" * 64,
        "index_version": "idx1",
        "metrics": {
            "recall@1": 0.4,
            "recall@3": 0.6,
            "recall@5": 0.7,
            "recall@10": 0.8,
            "mrr": 0.5,
        },
        "tolerance": 0.05,
    }


def make_result(**metric_overrides) -> dict:
    baseline = make_baseline()
    return {
        "index": {"version": "idx1"},
        "gold": {"sha256": baseline["gold_sha256"]},
        "config": copy.deepcopy(baseline["config"]),
        "metrics": {**baseline["metrics"], **metric_overrides},
    }


def test_same_metrics_pass():
    outcome = gate.compare(make_result(), make_baseline())
    assert outcome.passed and outcome.errors == []
    assert [c.name for c in outcome.checks] == [
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@10",
        "mrr",
    ]


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


def test_a_different_index_version_fails_with_refresh_instructions():
    result = make_result()
    result["index"]["version"] = "idx2"
    outcome = gate.compare(result, make_baseline())
    assert not outcome.passed
    message = outcome.errors[0]
    assert "idx2" in message and "idx1" in message
    assert "refresh the baseline" in message and "evals/baseline.json" in message
    assert "could not be fetched" in message


def test_a_different_gold_set_or_configuration_fails():
    result = make_result()
    result["gold"]["sha256"] = "h" * 64
    result["config"]["chunking"] = "neighbor"
    outcome = gate.compare(result, make_baseline())
    assert not outcome.passed
    assert any("gold set differs" in e for e in outcome.errors)
    assert any("chunking" in e and "neighbor" in e for e in outcome.errors)


def test_index_mismatch_helper():
    assert gate.index_mismatch("idx1", make_baseline()) is None
    assert "differs" in gate.index_mismatch("other", make_baseline())


def test_the_committed_baseline_passes_against_its_own_recorded_run():
    outcome = gate.compare(RECORDED, BASELINE)
    assert outcome.passed, outcome.errors
    assert BASELINE["index_version"] == RECORDED["index"]["version"]


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
    bad = write(tmp_path, "bad.json", make_result(mrr=0.1))
    summary = tmp_path / "summary.md"
    argv = ["compare", "--baseline", str(baseline), "--summary-file", str(summary)]

    assert gate.main([*argv, str(good)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert gate.main([*argv, str(bad)]) == 1
    assert "FAIL: mrr dropped" in capsys.readouterr().out
    report = summary.read_text()
    assert report.count("| metric |") == 2 and "PASS" in report and "FAIL" in report


def test_compare_command_missing_file_is_exit_2(tmp_path, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    assert gate.main(["compare", "--baseline", str(baseline), str(tmp_path / "nope.json")]) == 2
    assert "cannot read result" in capsys.readouterr().err


def fake_connect_to(monkeypatch, version):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(gate.db, "connect", lambda: Conn())
    monkeypatch.setattr(
        corpus_mod, "index_info", lambda conn: corpus_mod.IndexInfo(version, 235, 4482)
    )


def test_index_command_passes_on_the_baseline_version(tmp_path, monkeypatch, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    fake_connect_to(monkeypatch, "idx1")
    assert gate.main(["index", "--baseline", str(baseline)]) == 0
    assert "matches the baseline" in capsys.readouterr().out


def test_index_command_fails_on_another_version(tmp_path, monkeypatch, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())
    summary = tmp_path / "summary.md"
    fake_connect_to(monkeypatch, "idx9")
    assert gate.main(["index", "--baseline", str(baseline), "--summary-file", str(summary)]) == 1
    err = capsys.readouterr().err
    assert "FAIL" in err and "refresh the baseline" in err
    assert "refresh the baseline" in summary.read_text()


def test_index_command_database_down_is_exit_2(tmp_path, monkeypatch, capsys):
    baseline = write(tmp_path, "baseline.json", make_baseline())

    def refuse():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(gate.db, "connect", refuse)
    assert gate.main(["index", "--baseline", str(baseline)]) == 2
    assert "connection refused" in capsys.readouterr().err
