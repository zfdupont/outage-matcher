"""The agent with tracing off (the default) and with tracing on, using fakes for Langfuse."""

import pytest

from fakes import FakeAnthropic, FakeConn, make_hit, response, text_block, tool_block
from outage_matcher import cli, observability
from outage_matcher.agent import graph as graph_mod
from outage_matcher.agent import tools
from outage_matcher.agent.graph import OutageAgent
from outage_matcher.agent.tools import ToolContext
from outage_matcher.config import AgentConfig

QUESTION = "checkout latency spiked after a config push"


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    monkeypatch.setattr(
        tools,
        "search_chunks",
        lambda conn, query, model, k, **kw: [make_hit(1), make_hit(2, "summary", 0.5)],
    )


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")  # real client, no exporter
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")


def scripted(rewrites: int = 0) -> FakeAnthropic:
    """A run that retrieves, grades, optionally rewrites `rewrites` times, then answers."""

    def grades(flag):
        return response(tool_block("submit_grades", {"grades": [{"index": 0, "relevant": flag}]}))

    search = response(tool_block("search_incidents", {"query": "lb"}, "tu_s"))
    done = response(text_block("ok"))
    return FakeAnthropic(
        retrieve=[search, done] * (rewrites + 1),
        submit_grades=[grades(False)] * rewrites + [grades(True)],
        submit_query=[response(tool_block("submit_query", {"query": "second try"}))],
        submit_answer=[
            response(
                tool_block(
                    "submit_answer",
                    {"likely_cause": "Bad push.", "suggested_fix": "Roll back.", "citations": [1]},
                )
            )
        ],
    )


def make_agent(client) -> OutageAgent:
    return OutageAgent(client, ToolContext(FakeConn()), AgentConfig("fake-model", 2))


class SpyGraph:
    """Wraps the compiled graph and records the run config it was invoked with."""

    def __init__(self, inner):
        self.inner = inner
        self.configs = []

    def invoke(self, state, config=None):
        self.configs.append(config)
        return self.inner.invoke(state, config)


def test_agent_runs_with_tracing_disabled_and_touches_no_langfuse(no_keys, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("langfuse must not be touched when tracing is off")

    monkeypatch.setattr(observability, "_observed", boom)
    agent = make_agent(scripted())
    agent.graph = spy = SpyGraph(agent.graph)

    result = agent.ask(QUESTION)

    assert not result.answer.no_match
    assert [c.doc_id for c in result.answer.citations] == [1]
    assert "callbacks" not in spy.configs[0]  # no tracer, so no callback is attached


def test_tracer_is_attached_as_a_graph_callback_when_configured(no_keys, monkeypatch):
    # A fake langchain-style handler; tracing keys are not needed because get_tracer is faked.
    from langchain_core.callbacks import BaseCallbackHandler

    class Recorder(BaseCallbackHandler):
        def __init__(self):
            self.chain_names = []

        def on_chain_start(self, serialized, inputs, **kwargs):
            self.chain_names.append(kwargs.get("name"))

    recorder = Recorder()
    monkeypatch.setattr(graph_mod, "get_tracer", lambda: recorder)
    agent = make_agent(scripted())
    agent.graph = spy = SpyGraph(agent.graph)

    agent.ask(QUESTION)

    assert spy.configs[0]["callbacks"] == [recorder]
    assert {"retrieve", "grade", "answer"} <= set(recorder.chain_names)


def test_each_node_and_tool_call_is_wrapped_in_a_span(keys, monkeypatch):
    spans = []

    def fake_observed(func, name):
        def wrapper(*args, **kwargs):
            spans.append(("start", name))
            try:
                return func(*args, **kwargs)
            finally:
                spans.append(("end", name))

        return wrapper

    monkeypatch.setattr(observability, "_observed", fake_observed)
    monkeypatch.setattr(graph_mod, "get_tracer", lambda: None)

    make_agent(scripted(rewrites=1)).ask(QUESTION)

    started = [name for kind, name in spans if kind == "start"]
    assert started == [
        "node.retrieve",
        "tool.search_incidents",
        "node.grade",
        "node.rewrite",
        "node.retrieve",
        "tool.search_incidents",
        "node.grade",
        "node.answer",
    ]
    # A tool span opens and closes inside its node span.
    assert spans[:4] == [
        ("start", "node.retrieve"),
        ("start", "tool.search_incidents"),
        ("end", "tool.search_incidents"),
        ("end", "node.retrieve"),
    ]


def test_agent_runs_with_the_real_langfuse_objects_when_keys_are_set(keys):
    from langfuse.langchain import CallbackHandler

    agent = make_agent(scripted())
    agent.graph = spy = SpyGraph(agent.graph)

    result = agent.ask(QUESTION)

    assert not result.answer.no_match
    assert isinstance(spy.configs[0]["callbacks"][0], CallbackHandler)


def test_tool_errors_still_return_results_through_the_span(no_keys):
    agent = make_agent(scripted())
    result = agent._run_tool("no_such_tool", {})
    assert result.is_error and result.content["error"]["type"] == "unknown_tool"


# ----- flush ---------------------------------------------------------------------------------


def test_flush_is_a_noop_without_keys(no_keys, monkeypatch):
    import langfuse

    monkeypatch.setattr(
        langfuse, "get_client", lambda: (_ for _ in ()).throw(AssertionError("no client"))
    )
    observability.flush()


def test_flush_calls_the_client_when_keys_are_set(keys, monkeypatch):
    import langfuse

    calls = []

    class Client:
        def flush(self):
            calls.append("flush")

    monkeypatch.setattr(langfuse, "get_client", lambda: Client())
    observability.flush()
    assert calls == ["flush"]


def test_flush_never_raises(keys, monkeypatch):
    import langfuse

    def broken():
        raise RuntimeError("exporter down")

    monkeypatch.setattr(langfuse, "get_client", broken)
    observability.flush()


def test_ask_command_flushes_traces(monkeypatch, capsys):
    from test_cli import agent_result

    flushed = []
    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    monkeypatch.setattr("outage_matcher.config.load_dotenv", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(cli.observability, "flush", lambda: flushed.append(1))

    class Agent:
        def ask(self, question):
            return agent_result()

    from test_cli import fake_connect

    monkeypatch.setattr(cli.db, "connect", fake_connect)
    monkeypatch.setattr(cli, "_build_agent", lambda *a: Agent())
    monkeypatch.setattr(cli, "_make_client", lambda *a: "client")
    assert cli.main(["ask", "q"]) == 0
    assert flushed == [1]
