import pytest

from fakes import (
    FakeAnthropic,
    FakeConn,
    make_hit,
    response,
    text_block,
    tool_block,
)
from outage_matcher.agent import tools
from outage_matcher.agent.graph import OutageAgent
from outage_matcher.agent.models import NO_MATCH_CAUSE, RetrievalError
from outage_matcher.agent.tools import ToolContext
from outage_matcher.config import AgentConfig

QUESTION = "checkout latency spiked after a config push to our load balancers"


@pytest.fixture
def search_log(monkeypatch):
    """Fake the vector search; `results` maps a query to hits (default: docs 1 and 2)."""
    log = {"queries": [], "results": {}}

    def fake_search(conn, query, model, k, *, system_type=None, embedder=None):
        log["queries"].append((query, k, system_type))
        return log["results"].get(query, [make_hit(1), make_hit(2, "summary", 0.5)])

    monkeypatch.setattr(tools, "search_chunks", fake_search)
    return log


def search_call(query="lb config push", **extra):
    return response(tool_block("search_incidents", {"query": query, **extra}, "tu_s"))


def grades(*flags):
    return response(
        tool_block(
            "submit_grades", {"grades": [{"index": i, "relevant": f} for i, f in enumerate(flags)]}
        )
    )


def answer(citations, cause="Bad config push.", fix="Roll back the config."):
    return response(
        tool_block(
            "submit_answer",
            {"likely_cause": cause, "suggested_fix": fix, "citations": citations},
        ),
        tokens=(100, 40),
    )


def rewrite(query):
    return response(tool_block("submit_query", {"query": query}))


def make_agent(client, max_retries=2):
    return OutageAgent(client, ToolContext(FakeConn()), AgentConfig("fake-model", max_retries))


def test_tool_call_dispatch_and_answer_with_citations(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(k=2), response(text_block("found some"))],
        submit_grades=[grades(True, False)],
        submit_answer=[answer([1])],
    )
    result = make_agent(client).ask(QUESTION)

    assert search_log["queries"] == [("lb config push", 2, None)]
    # The tool result went back to the model in the follow-up turn, matched to the tool_use id.
    follow_up = client.calls_for("retrieve")[1]["messages"]
    assert follow_up[1]["role"] == "assistant"
    assert follow_up[1]["content"][0]["name"] == "search_incidents"
    tool_result = follow_up[2]["content"][0]
    assert tool_result["tool_use_id"] == "tu_s" and tool_result["is_error"] is False
    assert "Load balancer config push" in tool_result["content"]

    assert not result.answer.no_match
    assert [(c.doc_id, c.url) for c in result.answer.citations] == [(1, "https://x.test/lb")]
    assert result.answer.suggested_fix == "Roll back the config."
    assert result.retries == 0
    assert [e["type"] for e in result.events] == ["tool_call", "grade"]
    # 2 retrieve turns + grade + answer, with the scripted token counts.
    assert result.usage.llm_calls == 4
    assert (result.usage.input_tokens, result.usage.output_tokens) == (130, 55)
    assert all(c["model"] == "fake-model" for c in client.calls)


def test_malformed_tool_args_are_returned_to_the_model_not_raised(search_log):
    client = FakeAnthropic(
        retrieve=[
            response(
                tool_block("search_incidents", {"k": "lots"}, "bad_1"),
                tool_block("no_such_tool", {}, "bad_2"),
            ),
            search_call(),
            response(text_block("ok")),
        ],
        submit_grades=[grades(True, True)],
        submit_answer=[answer([1, 2])],
    )
    result = make_agent(client).ask(QUESTION)

    second_turn = client.calls_for("retrieve")[1]["messages"][2]["content"]
    assert [(r["tool_use_id"], r["is_error"]) for r in second_turn] == [
        ("bad_1", True),
        ("bad_2", True),
    ]
    assert "invalid_arguments" in second_turn[0]["content"]
    assert "unknown_tool" in second_turn[1]["content"]
    assert [e["is_error"] for e in result.events if e["type"] == "tool_call"] == [True, True, False]
    assert not result.answer.no_match and len(result.answer.citations) == 2


def test_retry_cap_terminates_with_no_match(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))] * 3,
        submit_grades=[grades(False, False)],
        submit_query=[rewrite("second try"), rewrite("third try")],
    )
    result = make_agent(client, max_retries=2).ask(QUESTION)

    assert result.retries == 2
    assert len(client.calls_for("submit_query")) == 2
    assert len(client.calls_for("submit_grades")) == 3  # initial attempt plus two retries
    assert client.calls_for("submit_answer") == []  # no LLM answer when nothing is relevant
    assert result.answer.no_match and result.answer.citations == []
    assert result.answer.likely_cause == NO_MATCH_CAUSE
    prompts = [
        c["messages"][0]["content"] for c in client.calls_for("retrieve") if len(c["messages"]) == 1
    ]
    assert [p.split("Search focus: ")[1].splitlines()[0] for p in prompts] == [
        QUESTION,
        "second try",
        "third try",
    ]


def test_zero_retries_never_rewrites(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(False, False)],
    )
    result = make_agent(client, max_retries=0).ask(QUESTION)
    assert result.retries == 0 and result.answer.no_match
    assert client.calls_for("submit_query") == []


def test_rewrite_feeds_the_next_retrieval_then_answers(search_log):
    search_log["results"] = {"lb config push": [make_hit(2, "other", 0.2)]}
    client = FakeAnthropic(
        retrieve=[
            search_call("lb config push"),
            response(text_block("ok")),
            search_call("bad configuration deploy load balancer"),
            response(text_block("ok")),
        ],
        submit_grades=[grades(False), grades(True, False)],
        submit_query=[rewrite("bad configuration deploy load balancer")],
        submit_answer=[answer([1])],
    )
    result = make_agent(client).ask(QUESTION)

    assert result.retries == 1
    retrieve_prompts = [c["messages"][0]["content"] for c in client.calls_for("retrieve")]
    assert "Search focus: bad configuration deploy load balancer" in retrieve_prompts[2]
    assert QUESTION in retrieve_prompts[2]  # past queries are listed so the model avoids repeats
    assert not result.answer.no_match
    assert [e["type"] for e in result.events if e["type"] in {"rewrite", "grade"}] == [
        "grade",
        "rewrite",
        "grade",
    ]


def test_answer_cannot_cite_a_document_that_was_not_retrieved(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(True, True)],
        submit_answer=[answer([1, 999, "2", True, 1])],
    )
    result = make_agent(client).ask(QUESTION)
    assert [c.doc_id for c in result.answer.citations] == [1, 2]
    assert len(result.answer.notes) == 2  # 999 and True were dropped
    assert "999" in result.answer.notes[0]


def test_answer_with_only_invalid_citations_degrades_to_no_match(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(True, True)],
        submit_answer=[answer([42])],
    )
    result = make_agent(client).ask(QUESTION)
    assert result.answer.no_match and result.answer.citations == []
    assert result.answer.likely_cause == NO_MATCH_CAUSE
    assert any("42" in n for n in result.answer.notes)


def test_citation_links_come_from_the_index_not_the_model(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(False, True)],
        submit_answer=[answer([2])],
    )
    citation = make_agent(client).ask(QUESTION).answer.citations[0]
    assert (citation.title, citation.url, citation.section) == (
        "Primary database failover",
        "https://x.test/db",
        "summary",
    )


def test_empty_retrieval_is_an_honest_no_match(search_log):
    search_log["results"] = {"lb config push": []}
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("nothing"))],
        submit_query=[rewrite("lb config push")],
    )
    result = make_agent(client, max_retries=1).ask(QUESTION)
    assert result.answer.no_match and result.retries == 1
    assert client.calls_for("submit_grades") == []  # nothing to grade
    assert client.calls_for("submit_answer") == []


def test_model_that_never_calls_a_tool_yields_no_match():
    client = FakeAnthropic(
        retrieve=[response(text_block("I know this one"))], submit_query=[rewrite("x")]
    )
    result = make_agent(client, max_retries=1).ask(QUESTION)
    assert result.answer.no_match and result.retries == 1


def test_malformed_grade_output_is_treated_as_not_relevant(search_log):
    bad = response(tool_block("submit_grades", {"grades": "everything"}))
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[bad],
    )
    result = make_agent(client, max_retries=0).ask(QUESTION)
    assert result.answer.no_match
    assert [e for e in result.events if e["type"] == "grade"][0]["malformed"] is True


def test_malformed_rewrite_falls_back_to_the_question_and_still_counts(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(False, False)],
        submit_query=[response(tool_block("submit_query", {"query": ""}))],
    )
    result = make_agent(client, max_retries=1).ask(QUESTION)
    assert result.retries == 1
    assert [e["query"] for e in result.events if e["type"] == "rewrite"] == [QUESTION]


def test_tool_turn_cap_stops_a_runaway_model(search_log):
    looping = response(tool_block("search_incidents", {"query": "again"}, "tu_loop"))
    client = FakeAnthropic(
        retrieve=[looping],  # repeats forever
        submit_grades=[grades(False, False)],
    )
    make_agent(client, max_retries=0).ask(QUESTION)
    assert len(client.calls_for("retrieve")) == 4


def test_backend_failure_raises_instead_of_reporting_no_match(monkeypatch):
    def broken_search(*args, **kwargs):
        raise RuntimeError("connection to the database was lost")

    monkeypatch.setattr(tools, "search_chunks", broken_search)
    client = FakeAnthropic(retrieve=[search_call(), response(text_block("ok"))])
    with pytest.raises(RetrievalError, match="search failed.*connection to the database was lost"):
        make_agent(client).ask(QUESTION)
    assert client.calls_for("submit_grades") == []  # failed fast, no retries or grading


def test_backend_failure_after_an_empty_search_still_raises(monkeypatch):
    calls = []

    def flaky_search(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return []
        raise RuntimeError("embedding model failed to load")

    monkeypatch.setattr(tools, "search_chunks", flaky_search)
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))] * 2,
        submit_query=[rewrite("again")],
    )
    with pytest.raises(RetrievalError, match="embedding model failed to load"):
        make_agent(client).ask(QUESTION)


def test_backend_failure_recovered_within_the_pass_is_not_an_error(monkeypatch):
    calls = []

    def flaky_search(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return [make_hit(1)]

    monkeypatch.setattr(tools, "search_chunks", flaky_search)
    client = FakeAnthropic(
        retrieve=[search_call(), search_call(), response(text_block("ok"))],
        submit_grades=[grades(True)],
        submit_answer=[answer([1])],
    )
    result = make_agent(client).ask(QUESTION)
    assert not result.answer.no_match
    assert [e["is_error"] for e in result.events if e["type"] == "tool_call"] == [True, False]


def test_model_mistakes_are_not_backend_failures(search_log):
    client = FakeAnthropic(
        retrieve=[response(tool_block("search_incidents", {"k": 3})), response(text_block("ok"))],
        submit_query=[rewrite("x")],
    )
    result = make_agent(client, max_retries=0).ask(QUESTION)
    assert result.answer.no_match  # invalid arguments stay a normal no-match, no exception


def test_empty_text_blocks_are_not_echoed_back_to_the_api(search_log):
    client = FakeAnthropic(
        retrieve=[
            response(
                text_block(""), text_block("  "), tool_block("search_incidents", {"query": "q"})
            ),
            response(text_block("ok")),
        ],
        submit_grades=[grades(False, False)],
    )
    make_agent(client, max_retries=0).ask(QUESTION)
    echoed = client.calls_for("retrieve")[1]["messages"][1]["content"]
    assert [b["type"] for b in echoed] == ["tool_use"]


def test_non_empty_text_blocks_are_echoed(search_log):
    client = FakeAnthropic(
        retrieve=[
            response(text_block("searching"), tool_block("search_incidents", {"query": "q"})),
            response(text_block("ok")),
        ],
        submit_grades=[grades(False, False)],
    )
    make_agent(client, max_retries=0).ask(QUESTION)
    echoed = client.calls_for("retrieve")[1]["messages"][1]["content"]
    assert [b["type"] for b in echoed] == ["text", "tool_use"]


def test_result_carries_every_retrieved_chunk_as_evidence(search_log):
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(True, False)],
        submit_answer=[answer([1])],
    )
    result = make_agent(client).ask(QUESTION)
    assert sorted(c.doc_id for c in result.evidence) == [1, 2]
    assert result.evidence[0].text == "text of doc 1"


def test_evidence_lists_the_chunks_the_answerer_saw_before_the_rest(search_log):
    # the grader accepts only doc 2, which was retrieved second
    client = FakeAnthropic(
        retrieve=[search_call(), response(text_block("ok"))],
        submit_grades=[grades(False, True)],
        submit_answer=[answer([2])],
    )
    result = make_agent(client).ask(QUESTION)
    assert [c.doc_id for c in result.evidence] == [2, 1]
