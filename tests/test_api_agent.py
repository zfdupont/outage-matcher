from contextlib import contextmanager

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeAnthropic, FakeConn, make_hit, response, text_block, tool_block
from outage_matcher import cli
from outage_matcher.agent import tools
from outage_matcher.agent.graph import OutageAgent
from outage_matcher.agent.models import (
    NO_MATCH_CAUSE,
    AgentAnswer,
    AgentResult,
    Citation,
    RetrievalError,
    Usage,
)
from outage_matcher.agent.tools import ToolContext
from outage_matcher.api.agent import ApiAgent, to_response
from outage_matcher.api.app import create_app
from outage_matcher.config import AgentConfig


def result(no_match=False) -> AgentResult:
    if no_match:
        answer = AgentAnswer(NO_MATCH_CAUSE, "Add detail.", no_match=True)
    else:
        cite = Citation(7, "LB outage", "https://x.test/lb", "root_cause")
        answer = AgentAnswer("Bad config push.", "Roll back.", [cite])
    return AgentResult("q", answer, Usage(10, 5, 2), 0, [])


def test_to_response_maps_answer_and_citations():
    resp = to_response(result())
    assert resp.likely_cause == "Bad config push."
    assert resp.suggested_fix == "Roll back."
    assert resp.answer == "Likely cause: Bad config push.\nSuggested fix: Roll back."
    assert [c.model_dump() for c in resp.citations] == [
        {"doc_id": "7", "title": "LB outage", "url": "https://x.test/lb", "section": "root_cause"}
    ]


def test_to_response_no_match_has_no_citations():
    resp = to_response(result(no_match=True))
    assert resp.citations == []
    assert NO_MATCH_CAUSE in resp.answer


def test_api_agent_opens_and_closes_one_connection_per_request():
    events = []

    @contextmanager
    def connect():
        events.append("open")
        yield "conn"
        events.append("close")

    class Bound:
        def __init__(self, conn):
            self.conn = conn

        def ask(self, question):
            events.append(f"ask {question} on {self.conn}")
            return result()

    agent = ApiAgent(Bound, connect)
    agent.ask("one")
    agent.ask("two")
    assert events == [
        "open",
        "ask one on conn",
        "close",
        "open",
        "ask two on conn",
        "close",
    ]


def test_connection_is_closed_and_the_error_propagates_when_the_agent_fails():
    events = []

    @contextmanager
    def connect():
        try:
            yield "conn"
        finally:
            events.append("closed")

    class Broken:
        def __init__(self, conn):
            pass

        def ask(self, question):
            raise RetrievalError("db down")

    with pytest.raises(RetrievalError):
        ApiAgent(Broken, connect).ask("q")
    assert events == ["closed"]


def test_unreachable_database_is_503():
    import psycopg

    http = TestClient(
        create_app(lambda: Raises(psycopg.OperationalError("host=db password=hunter2 refused"))),
        raise_server_exceptions=False,
    )
    resp = http.post("/ask", json={"question": "q"})
    assert resp.status_code == 503
    assert "hunter2" not in resp.text


def test_ask_endpoint_runs_the_real_graph_with_fake_model_and_search(monkeypatch):
    def fake_search(conn, query, model, k, *, system_type=None, embedder=None, **extra):
        return [make_hit(1), make_hit(2, "summary", 0.5)]

    monkeypatch.setattr(tools, "search_chunks", fake_search)
    client = FakeAnthropic(
        retrieve=[
            response(tool_block("search_incidents", {"query": "lb config push"}, "tu_s")),
            response(text_block("found")),
        ],
        submit_grades=[
            response(
                tool_block(
                    "submit_grades",
                    {"grades": [{"index": 0, "relevant": True}, {"index": 1, "relevant": False}]},
                )
            )
        ],
        submit_answer=[
            response(
                tool_block(
                    "submit_answer",
                    {
                        "likely_cause": "Bad regex in a config push.",
                        "suggested_fix": "Roll back the push.",
                        "citations": [1],
                    },
                )
            )
        ],
    )
    config = AgentConfig("fake-model", 2)

    @contextmanager
    def connect():
        yield FakeConn()

    agent = ApiAgent(lambda conn: OutageAgent(client, ToolContext(conn), config), connect)
    http = TestClient(create_app(lambda: agent))
    resp = http.post("/ask", json={"question": "checkout latency spiked after a config push"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["likely_cause"] == "Bad regex in a config push."
    assert body["suggested_fix"] == "Roll back the push."
    assert body["citations"] == [
        {
            "doc_id": "1",
            "title": "Load balancer config push",
            "url": "https://x.test/lb",
            "section": "root_cause",
        }
    ]
    assert "Bad regex" in body["answer"]


class Raises:
    def __init__(self, exc):
        self.exc = exc

    def ask(self, question):
        raise self.exc


def test_retrieval_failure_is_503_not_a_no_match():
    exc = RetrievalError("search failed: password=hunter2 refused")
    http = TestClient(create_app(lambda: Raises(exc)), raise_server_exceptions=False)
    resp = http.post("/ask", json={"question": "q"})
    assert resp.status_code == 503
    assert resp.json() == {"error": {"status": 503, "message": "search backend unavailable"}}
    assert "hunter2" not in resp.text


def test_model_api_failure_is_502_without_detail():
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.test/secret"))
    http = TestClient(create_app(lambda: Raises(exc)), raise_server_exceptions=False)
    resp = http.post("/ask", json={"question": "q"})
    assert resp.status_code == 502
    assert resp.json() == {"error": {"status": 502, "message": "model API call failed"}}
    assert "secret" not in resp.text


# ----- the serve command's factory ---------------------------------------------------------


def test_serve_factory_is_none_without_a_real_key(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.serve_agent_factory() is None
    assert "POST /ask will answer 503" in capsys.readouterr().err
    http = TestClient(create_app(cli.serve_agent_factory))
    assert http.get("/health").status_code == 200
    assert http.post("/ask", json={"question": "q"}).status_code == 503


def test_serve_factory_builds_the_agent_per_request_connection(monkeypatch):
    from outage_matcher import config as config_mod

    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    monkeypatch.setattr(config_mod, "load_dotenv", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    seen = {}

    class Bound:
        def ask(self, question):
            seen["question"] = question
            return result()

    monkeypatch.setattr(cli, "_make_client", lambda key, config: ("client", key))

    def build_agent(conn, client, config):
        seen["args"] = (conn, client)
        return Bound()

    monkeypatch.setattr(cli, "_build_agent", build_agent)

    @contextmanager
    def connect():
        yield "conn"

    monkeypatch.setattr("outage_matcher.api.agent.open_connection", connect)
    agent = cli.serve_agent_factory()
    http = TestClient(create_app(lambda: agent))
    resp = http.post("/ask", json={"question": "why"})
    assert resp.status_code == 200
    assert seen["question"] == "why"
    assert seen["args"] == ("conn", ("client", "sk-test-not-real"))
