import json
from contextlib import contextmanager

import pytest

from outage_matcher import cli
from outage_matcher.ingest.collect import ManifestEntry
from outage_matcher.search import SearchHit


@contextmanager
def fake_connect():
    yield object()


def hit(title: str, score: float) -> SearchHit:
    return SearchHit(title, "root_cause", score, f"https://x.test/{title}", "database", "text")


def test_search_prints_both_models_with_citations(monkeypatch, capsys):
    calls = []

    def fake_search(conn, query, model, k, system_type=None):
        calls.append((query, model, k, system_type))
        return [hit(f"{model}-doc", 0.8123)]

    monkeypatch.setattr(cli.db, "connect", fake_connect)
    monkeypatch.setattr(cli, "search", fake_search)
    assert cli.main(["search", "database failover caused split brain"]) == 0
    out = capsys.readouterr().out
    assert [c[1] for c in calls] == ["bge", "minilm"]
    assert "== bge (BAAI/bge-small-en-v1.5)" in out
    assert "== minilm (sentence-transformers/all-MiniLM-L6-v2)" in out
    assert "1. bge-doc [root_cause] score=0.812" in out
    assert "https://x.test/minilm-doc" in out


def test_search_single_model_k_and_filter(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli.db, "connect", fake_connect)
    monkeypatch.setattr(cli, "search", lambda *a, **kw: calls.append((a[2:], kw)) or [])
    cli.main(["search", "q", "--model", "minilm", "--k", "3", "--system-type", "network"])
    assert calls == [(("minilm", 3), {"system_type": "network"})]
    assert "no results" in capsys.readouterr().out


def test_search_rejects_unknown_model():
    with pytest.raises(SystemExit):
        cli.main(["search", "q", "--model", "nope"])


def test_ingest_skip_collect_without_manifest_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["ingest", "--skip-collect"]) == 1
    assert "no manifest" in capsys.readouterr().err


def test_ingest_runs_stages_and_writes_stats(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"  # relative paths in the CLI resolve against the chdir above
    (data / "raw").mkdir(parents=True)
    entry = ManifestEntry("d1", "https://x.test/a", "A", "community", "2026-11-13", "database")
    (data / "raw" / "d1.html").write_text(
        "<html><body><h1>T</h1><p>"
        + "The primary failed and replicas lagged behind. " * 5
        + "</p></body></html>"
    )
    monkeypatch.setattr(cli.collect_mod, "collect", lambda **kw: ([entry], []))
    monkeypatch.setattr(cli.db, "connect", fake_connect)
    written = {}

    def fake_write_index(conn, docs, log=None):
        written["docs"] = docs
        return cli.index_mod.IndexResult(
            documents=len(docs), chunks=sum(len(d.chunks) for d in docs)
        )

    monkeypatch.setattr(cli.index_mod, "write_index", fake_write_index)
    assert cli.main(["ingest"]) == 0
    assert "indexed 1 documents" in capsys.readouterr().out
    stats = json.loads((data / "corpus_stats.json").read_text())
    assert stats["document_count"] == 1 and stats["per_source"]["community"]["documents"] == 1
