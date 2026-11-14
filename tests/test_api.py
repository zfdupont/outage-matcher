import pytest
from fastapi.testclient import TestClient

from outage_matcher import cli
from outage_matcher.api.app import create_app
from outage_matcher.api.models import AskResponse, Citation


def canned() -> AskResponse:
    return AskResponse(
        answer="The cache stampede overloaded the database.",
        likely_cause="Cache expiry storm",
        suggested_fix="Add jittered TTLs",
        citations=[
            Citation(doc_id="12", title="Cache storm", url="https://x.test/a", section="rca")
        ],
    )


class FakeAgent:
    def __init__(self):
        self.questions: list[str] = []

    def ask(self, question: str) -> AskResponse:
        self.questions.append(question)
        return canned()


class BrokenAgent:
    def ask(self, question: str) -> AskResponse:
        raise RuntimeError("secret internal detail /srv/app.py line 3")


def test_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ask_returns_agent_response():
    agent = FakeAgent()
    client = TestClient(create_app(lambda: agent))
    resp = client.post("/ask", json={"question": "  db latency spiked after deploy  "})
    assert resp.status_code == 200
    assert resp.json() == canned().model_dump()
    assert agent.questions == ["db latency spiked after deploy"]


def test_ask_without_agent_is_503_json():
    client = TestClient(create_app())
    resp = client.post("/ask", json={"question": "anything"})
    assert resp.status_code == 503
    assert resp.json()["error"]["status"] == 503
    assert "not available" in resp.json()["error"]["message"]


def test_agent_factory_is_called_once_and_lazily():
    calls = []

    def factory():
        calls.append(1)
        return FakeAgent()

    client = TestClient(create_app(factory))
    client.get("/health")
    assert calls == []
    client.post("/ask", json={"question": "a"})
    client.post("/ask", json={"question": "b"})
    assert calls == [1]


@pytest.mark.parametrize(
    "payload",
    [{}, {"question": ""}, {"question": "   "}, {"question": 5}, {"question": "x" * 4001}],
)
def test_ask_rejects_bad_input_with_422(payload):
    client = TestClient(create_app(FakeAgent))
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["status"] == 422
    assert body["error"]["detail"][0]["field"] == "question" or payload == {}


def test_ask_rejects_malformed_json():
    client = TestClient(create_app(FakeAgent))
    resp = client.post("/ask", content=b"{nope", headers={"content-type": "application/json"})
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_unknown_route_and_wrong_method_are_json_errors():
    client = TestClient(create_app())
    missing = client.get("/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["status"] == 404
    wrong = client.get("/ask")
    assert wrong.status_code == 405
    assert wrong.json()["error"]["status"] == 405


def test_agent_failure_is_500_without_stack_trace():
    client = TestClient(create_app(BrokenAgent), raise_server_exceptions=False)
    resp = client.post("/ask", json={"question": "q"})
    assert resp.status_code == 500
    assert resp.json() == {"error": {"status": 500, "message": "internal server error"}}
    assert "secret" not in resp.text
    assert "Traceback" not in resp.text


def test_factory_failure_is_500():
    def factory():
        raise RuntimeError("cannot build agent")

    client = TestClient(create_app(factory), raise_server_exceptions=False)
    resp = client.post("/ask", json={"question": "q"})
    assert resp.status_code == 500
    assert "cannot build" not in resp.text


def test_serve_command_runs_uvicorn(monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9000"]) == 0
    assert seen["host"] == "0.0.0.0"
    assert seen["port"] == 9000
    assert TestClient(seen["app"]).get("/health").status_code == 200


def test_serve_defaults_to_localhost(monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    cli.main(["serve"])
    assert seen == {"host": "127.0.0.1", "port": 8000}
