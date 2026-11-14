import json

import pytest

from fakes import FakeConn, make_hit
from outage_matcher.agent import tools
from outage_matcher.agent.tools import TOOL_DEFINITIONS, ToolContext, run_tool


@pytest.fixture
def ctx():
    return ToolContext(conn=FakeConn())


@pytest.fixture
def searches(monkeypatch):
    calls = []

    def fake_search(conn, query, model, k, *, system_type=None, embedder=None):
        calls.append((query, model, k, system_type))
        return [make_hit(1), make_hit(2, score=0.5)]

    monkeypatch.setattr(tools, "search_chunks", fake_search)
    return calls


def test_definitions_are_valid_anthropic_tool_schemas():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert names == ["search_incidents", "get_postmortem", "filter_by_system_type"]
    for tool in TOOL_DEFINITIONS:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
        assert set(tool["input_schema"]["required"]) <= set(tool["input_schema"]["properties"])
    json.dumps(TOOL_DEFINITIONS)


def test_search_incidents_dispatch_and_retrieved(ctx, searches):
    result = run_tool(ctx, "search_incidents", {"query": "lb latency", "k": 2})
    assert not result.is_error
    assert searches == [("lb latency", "bge", 2, None)]
    assert [c.doc_id for c in result.retrieved] == [1, 2]
    assert result.content["results"][0]["doc_id"] == 1
    assert result.content["results"][0]["score"] == 0.8
    json.dumps(result.content)


def test_search_incidents_defaults_and_system_type(ctx, searches):
    run_tool(ctx, "search_incidents", {"query": "q", "system_type": "network"})
    assert searches == [("q", "bge", 5, "network")]


def test_search_incidents_accepts_numeric_string_k(ctx, searches):
    run_tool(ctx, "search_incidents", {"query": "q", "k": "3"})
    assert searches[0][2] == 3


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": ""},
        {"query": 7},
        {"query": "q", "k": "many"},
        {"query": "q", "k": True},
        {"query": "q", "k": 0},
        {"query": "q", "k": 999},
        {"query": "q", "system_type": 3},
        "not an object",
        None,
        ["query"],
    ],
)
def test_malformed_search_args_return_error_result(ctx, searches, args):
    result = run_tool(ctx, "search_incidents", args)
    assert result.is_error
    assert result.content["error"]["type"] == "invalid_arguments"
    assert searches == []
    assert result.retrieved == []


def test_unknown_tool_is_an_error_result(ctx):
    result = run_tool(ctx, "drop_tables", {})
    assert result.is_error and result.content["error"]["type"] == "unknown_tool"


def test_unknown_system_type_lists_valid_types(ctx, searches):
    result = run_tool(ctx, "search_incidents", {"query": "q", "system_type": "toaster"})
    assert result.is_error
    assert result.content["error"]["type"] == "unknown_system_type"
    assert "network" in result.content["error"]["message"]
    assert searches == []


def test_get_postmortem_returns_document_and_marks_it_retrieved(ctx):
    result = run_tool(ctx, "get_postmortem", {"doc_id": 1})
    assert not result.is_error
    assert result.content["title"] == "Load balancer config push"
    assert "[root_cause] Bad regex." in result.content["text"]
    assert [c.doc_id for c in result.retrieved] == [1]


def test_get_postmortem_truncates_long_documents(ctx, monkeypatch):
    monkeypatch.setattr(tools, "DOCUMENT_CHARS", 30)
    result = run_tool(ctx, "get_postmortem", {"doc_id": 1})
    assert len(result.content["text"]) <= 30
    assert result.content["truncated"] is True


@pytest.mark.parametrize("args", [{"doc_id": 99}, {"doc_id": "abc"}, {}, {"doc_id": 1.5}])
def test_get_postmortem_bad_input(ctx, args):
    result = run_tool(ctx, "get_postmortem", args)
    assert result.is_error
    assert result.content["error"]["type"] in {"not_found", "invalid_arguments"}


def test_filter_by_system_type_with_query_searches_within_type(ctx, searches):
    result = run_tool(ctx, "filter_by_system_type", {"system_type": "database", "query": "q"})
    assert not result.is_error
    assert searches == [("q", "bge", 5, "database")]


def test_filter_by_system_type_without_query_lists_documents(ctx, searches):
    result = run_tool(ctx, "filter_by_system_type", {"system_type": "database"})
    assert result.content["documents"] == [
        {"doc_id": 2, "title": "Primary database failover", "url": "https://x.test/db"}
    ]
    assert result.retrieved == []  # a listing is not evidence
    assert searches == []


def test_filter_by_system_type_rejects_unknown_type(ctx):
    result = run_tool(ctx, "filter_by_system_type", {"system_type": "toaster"})
    assert result.is_error and result.content["error"]["type"] == "unknown_system_type"


def test_backend_exception_becomes_error_and_rolls_back(ctx, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("database is down")

    monkeypatch.setattr(tools, "search_chunks", boom)
    result = run_tool(ctx, "search_incidents", {"query": "q"})
    assert result.is_error
    assert result.content["error"]["type"] == "tool_failed"
    assert "database is down" in result.content["error"]["message"]
    assert ctx.conn.rollbacks == 1


@pytest.mark.db
def test_tools_against_real_index():
    from outage_matcher import db

    with db.connect() as conn:
        c = ToolContext(conn)
        listing = run_tool(c, "filter_by_system_type", {"system_type": "network"})
        assert listing.content["count"] > 0
        doc_id = listing.content["documents"][0]["doc_id"]
        doc = run_tool(c, "get_postmortem", {"doc_id": doc_id})
        assert doc.content["text"] and not doc.is_error
        found = run_tool(c, "search_incidents", {"query": "load balancer config push", "k": 3})
        assert found.content["count"] == 3
        assert found.retrieved[0].doc_id > 0


def test_hidden_chunks_are_passed_to_search_only_when_set(monkeypatch):
    seen = []

    def fake_search(conn, query, model, k, **kwargs):
        seen.append(kwargs)
        return []

    monkeypatch.setattr(tools, "search_chunks", fake_search)
    tools.run_tool(ToolContext(FakeConn()), "search_incidents", {"query": "q"})
    tools.run_tool(
        ToolContext(FakeConn(), exclude_chunk_ids=frozenset({4, 2})),
        "search_incidents",
        {"query": "q"},
    )
    assert "exclude_chunk_ids" not in seen[0]
    assert seen[1]["exclude_chunk_ids"] == frozenset({2, 4})


def test_get_postmortem_leaves_out_hidden_chunks():
    class Recording(FakeConn):
        def __init__(self):
            super().__init__()
            self.chunk_queries = []

        def execute(self, sql, params=()):
            if "FROM chunks WHERE postmortem_id" in sql:
                self.chunk_queries.append((sql, params))
            return super().execute(sql, params)

    conn = Recording()
    tools.run_tool(ToolContext(conn), "get_postmortem", {"doc_id": 1})
    tools.run_tool(
        ToolContext(conn, exclude_chunk_ids=frozenset({7, 3})), "get_postmortem", {"doc_id": 1}
    )
    (plain_sql, plain_params), (hidden_sql, hidden_params) = conn.chunk_queries
    assert "<> ALL" not in plain_sql and plain_params == (1,)
    assert "id <> ALL(%s::int[])" in hidden_sql and hidden_params == (1, [3, 7])
