import json
from contextlib import contextmanager

import psycopg
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


def test_ingest_skip_collect_reuses_manifest_and_recorded_failures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    entry = ManifestEntry("d1", "https://x.test/a", "A", "github", "2026-11-13", "database")
    (data / "manifest.jsonl").write_text(json.dumps(entry.__dict__) + "\n")
    (data / "collect_failures.jsonl").write_text(
        json.dumps({"url": "u", "source": "community", "reason": "http 404"}) + "\n"
    )
    (data / "raw" / "d1.html").write_text(
        "<html><body><h1>T</h1><p>"
        + "The primary failed and replicas lagged behind. " * 5
        + "</p></body></html>"
    )
    monkeypatch.setattr(cli.db, "connect", fake_connect)
    monkeypatch.setattr(
        cli.index_mod, "write_index", lambda conn, docs, log=None: cli.index_mod.IndexResult()
    )

    def no_network(**kw):
        raise AssertionError("collect must not run with --skip-collect")

    monkeypatch.setattr(cli.collect_mod, "collect", no_network)
    assert cli.main(["ingest", "--skip-collect"]) == 0
    stats = json.loads((data / "corpus_stats.json").read_text())
    assert stats["failures"]["collect"] == 1 and stats["document_count"] == 1


def test_ingest_with_no_chunkable_documents_leaves_index_and_stats_untouched(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    entry = ManifestEntry("gone", "https://x.test/a", "A", "github", "2026-11-13", "database")
    (data / "manifest.jsonl").write_text(json.dumps(entry.__dict__) + "\n")  # no data/raw files

    def no_db():
        raise AssertionError("must not connect to the database")

    monkeypatch.setattr(cli.db, "connect", no_db)
    assert cli.main(["ingest", "--skip-collect"]) == 1
    assert "left unchanged" in capsys.readouterr().err
    assert not (data / "corpus_stats.json").exists()


@pytest.mark.parametrize("bad", ["0", "-3", "x"])
def test_search_rejects_non_positive_k(bad):
    with pytest.raises(SystemExit):
        cli.main(["search", "q", "--k", bad])


def test_unreachable_database_is_a_one_line_error(monkeypatch, capsys):
    def refuse():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(cli.db, "connect", refuse)
    assert cli.main(["search", "q"]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "error: connection refused"


def test_missing_database_url_is_a_one_line_error(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli.db, "load_dotenv", lambda: False)
    assert cli.main(["search", "q"]) == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().err


# ----- ask ------------------------------------------------------------------------------------


class FakeAgent:
    def __init__(self, result):
        self.result = result
        self.questions = []

    def ask(self, question):
        self.questions.append(question)
        return self.result


def agent_result(no_match=False):
    from outage_matcher.agent.models import AgentAnswer, AgentResult, Citation, Usage

    if no_match:
        answer = AgentAnswer("No close match.", "Add detail.", no_match=True)
    else:
        cite = Citation(7, "LB outage", "https://x.test/lb", "root_cause")
        answer = AgentAnswer("Bad config push.", "Roll back.", [cite])
    events = [
        {
            "type": "tool_call",
            "name": "search_incidents",
            "input": {"query": "q"},
            "is_error": False,
            "doc_ids": [7],
            "error": None,
        },
        {"type": "grade", "graded": 5, "relevant": 2},
    ]
    return AgentResult("checkout is slow", answer, Usage(300, 90, 4), 1, events)


@pytest.fixture
def ask_env(monkeypatch):
    from outage_matcher import config

    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MAX_RETRIES", raising=False)
    monkeypatch.setattr(cli.db, "connect", fake_connect)


def test_ask_prints_answer_citations_and_usage(ask_env, monkeypatch, capsys):
    agent = FakeAgent(agent_result())
    monkeypatch.setattr(cli, "_build_agent", lambda conn, key, config: agent)
    assert cli.main(["ask", "checkout is slow"]) == 0
    out = capsys.readouterr().out
    assert agent.questions == ["checkout is slow"]
    assert "Likely cause: Bad config push." in out
    assert "Suggested fix: Roll back." in out
    assert "[7] LB outage (root_cause)" in out and "https://x.test/lb" in out
    assert "Usage: 4 LLM calls, 300 input tokens, 90 output tokens, 1 query rewrites" in out


def test_ask_no_match_says_so(ask_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_build_agent", lambda *a: FakeAgent(agent_result(no_match=True)))
    assert cli.main(["ask", "q"]) == 0
    assert "Citations: none" in capsys.readouterr().out


@pytest.mark.parametrize("key", [None, "", "your-key-here"])
def test_ask_without_a_real_key_stops_with_a_note(monkeypatch, capsys, key):
    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)

    def no_db():
        raise AssertionError("must not touch the database without a key")

    monkeypatch.setattr(cli.db, "connect", no_db)
    assert cli.main(["ask", "q"]) == 1
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY is not set" in err and "Traceback" not in err


def test_ask_writes_transcript(ask_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_build_agent", lambda *a: FakeAgent(agent_result()))
    target = tmp_path / "examples" / "run.md"
    assert cli.main(["ask", "checkout is slow", "--transcript", str(target)]) == 0
    text = target.read_text()
    assert "## Question\n\ncheckout is slow" in text
    assert "- tool `search_incidents`" in text and "- grade: 2 of 5 chunks relevant" in text
    assert "Model: claude-haiku-5-5" in text and "Usage: 4 LLM calls" in text


def test_ask_api_error_is_a_one_line_error(ask_env, monkeypatch, capsys):
    import anthropic
    import httpx

    class Boom:
        def ask(self, question):
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x.test"))

    monkeypatch.setattr(cli, "_build_agent", lambda *a: Boom())
    assert cli.main(["ask", "q"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: Anthropic API call failed") and "Traceback" not in err


def test_ask_search_failure_is_a_one_line_error_not_a_no_match(ask_env, monkeypatch, capsys):
    from outage_matcher.agent.models import RetrievalError

    class Broken:
        def ask(self, question):
            raise RetrievalError("search failed: database is down; this is not a no-match result")

    monkeypatch.setattr(cli, "_build_agent", lambda *a: Broken())
    assert cli.main(["ask", "q"]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: search failed: database is down")
    assert "No close match" not in captured.out and "Traceback" not in captured.err
