import json

import pytest

from outage_matcher.agent.models import AgentAnswer, AgentResult, Citation, RetrievalError, Usage
from outage_matcher.agent.tools import RetrievedChunk
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals import faithfulness, run_faithfulness
from outage_matcher.evals.deepseek import ChatResult, DeepSeekError, TokenUsage
from outage_matcher.evals.gold import write_gold
from test_evals_retrieval import gold_row


def chunk(doc_id, text="text", section="root_cause"):
    return RetrievedChunk(doc_id, f"Doc {doc_id}", f"https://x.test/{doc_id}", section, "net", text)


def agent_result(cited=(1,), no_match=False, evidence=None):
    answer = AgentAnswer(
        "Bad config push.",
        "Roll it back.",
        [Citation(d, f"Doc {d}", f"https://x.test/{d}", "root_cause") for d in cited],
        no_match=no_match,
    )
    evidence = evidence if evidence is not None else [chunk(1, "A config push broke it."), chunk(2)]
    return AgentResult("q", answer, Usage(100, 20, 3), 0, [], evidence)


class FakeJudge:
    model = "deepseek-flash"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat_json(self, messages, *, temperature=0.0, max_tokens=1024):
        self.calls.append({"messages": messages, "temperature": temperature})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(reply, json.dumps(reply), TokenUsage(50, 10, 1))


def verdict(*flags):
    return {
        "claims": [
            {"claim": f"claim {i}", "supported": f, "reason": "r"} for i, f in enumerate(flags)
        ]
    }


def test_cited_evidence_keeps_only_chunks_of_cited_documents_once():
    result = agent_result(
        cited=(1,), evidence=[chunk(1, "a"), chunk(2, "b"), chunk(1, "a"), chunk(1, "c", "impact")]
    )
    assert [(c.doc_id, c.text) for c in faithfulness.cited_evidence(result)] == [(1, "a"), (1, "c")]


def test_cited_evidence_truncates_long_chunks_and_caps_the_total():
    long = "x" * (faithfulness.EVIDENCE_CHARS + 500)
    many = [chunk(1, f"{i}" + long, "impact") for i in range(10)]
    evidence = faithfulness.cited_evidence(agent_result(evidence=many))
    assert all(len(c.text) <= faithfulness.EVIDENCE_CHARS for c in evidence)
    assert sum(len(c.text) for c in evidence) <= faithfulness.MAX_EVIDENCE_CHARS


def test_judge_prompt_contains_excerpts_and_the_answer_text():
    result = agent_result()
    prompt = faithfulness.judge_prompt(result, faithfulness.cited_evidence(result))
    assert "A config push broke it." in prompt
    assert "Likely cause: Bad config push." in prompt and "Suggested fix: Roll it back." in prompt
    assert "[doc 1]" in prompt and "[doc 2]" not in prompt


def test_judge_answer_uses_temperature_zero_and_returns_claims_and_usage():
    judge = FakeJudge(verdict(True, False))
    judgment = faithfulness.judge_answer(judge, agent_result())
    assert [(c.claim, c.supported) for c in judgment.claims] == [
        ("claim 0", True),
        ("claim 1", False),
    ]
    assert judge.calls[0]["temperature"] == 0.0
    assert judgment.usage == TokenUsage(50, 10, 1)


def test_judge_answer_retries_once_on_a_malformed_verdict_then_gives_up():
    judge = FakeJudge({"claims": "none"}, verdict(True))
    assert len(faithfulness.judge_answer(judge, agent_result()).claims) == 1
    assert judge.calls and len(judge.calls) == 2
    with pytest.raises(DeepSeekError, match="no usable verdict"):
        faithfulness.judge_answer(FakeJudge({"claims": []}, {"x": 1}), agent_result())


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"claims": [{"claim": "a"}]},
        {"claims": [{"claim": "", "supported": True}]},
        {"claims": ["a"]},
    ],
)
def test_parse_claims_rejects_incomplete_verdicts(data):
    with pytest.raises(ValueError):
        faithfulness.parse_claims(data)


def test_summarize_counts_no_match_and_errors_separately_from_scores():
    records = [
        {"claims": [{"supported": True}, {"supported": True}], "no_match": False},
        {"claims": [{"supported": True}, {"supported": False}], "no_match": False},
        {"claims": [], "no_match": True},
        {"claims": [], "no_match": False, "error": "boom"},
    ]
    summary = faithfulness.summarize(records)
    assert summary["queries"] == 4 and summary["answered_and_judged"] == 2
    assert summary["no_match"] == 1 and summary["errors"] == 1
    assert (summary["claims"], summary["claims_supported"]) == (4, 3)
    assert summary["claim_support_rate"] == 0.75
    assert summary["faithful_answer_rate"] == 0.5


def test_summarize_with_nothing_judged_has_no_rates():
    summary = faithfulness.summarize([{"claims": [], "no_match": True}])
    assert summary["claim_support_rate"] is None and summary["faithful_answer_rate"] is None


class FakeAgent:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def ask(self, question):
        if self.error:
            raise self.error
        return self.result


def test_run_all_records_per_query_outcomes_and_the_source_citation():
    gold = [gold_row("q001", 1, "q", [2]), gold_row("q002", 2, "q", [1])]
    agents = {
        "q001": FakeAgent(agent_result(cited=(1,))),
        "q002": FakeAgent(agent_result(cited=(), no_match=True)),
    }
    records = run_faithfulness.run_all(gold, lambda row: agents[row.id], FakeJudge(verdict(True)))
    first, second = records
    assert first["cited_source_doc"] is True and first["cited_doc_ids"] == [1]
    assert first["agent_usage"] == {"input_tokens": 100, "output_tokens": 20, "llm_calls": 3}
    assert first["judge_usage"]["input_tokens"] == 50 and len(first["claims"]) == 1
    assert second["no_match"] is True and second["claims"] == []
    assert run_faithfulness.sum_usage(records, "agent_usage")["calls"] == 6


def test_run_all_records_a_failed_query_and_keeps_going():
    gold = [gold_row("q001", 1, "q", [2]), gold_row("q002", 2, "q", [1])]
    agents = {
        "q001": FakeAgent(error=RetrievalError("db down")),
        "q002": FakeAgent(agent_result()),
    }
    records = run_faithfulness.run_all(gold, lambda row: agents[row.id], FakeJudge(verdict(True)))
    assert "db down" in records[0]["error"] and records[1]["error"] is None


def test_run_all_stops_after_consecutive_failures():
    gold = [gold_row(f"q{i:03d}", 1, "q", [2]) for i in range(5)]
    failing = FakeAgent(error=RetrievalError("nope"))
    with pytest.raises(RuntimeError, match="3 queries failed in a row"):
        run_faithfulness.run_all(gold, lambda row: failing, FakeJudge())


def test_run_all_does_not_swallow_programming_errors():
    gold = [gold_row("q001", 1, "q", [2])]
    with pytest.raises(KeyError):
        run_faithfulness.run_all(gold, lambda row: FakeAgent(error=KeyError("bug")), FakeJudge())


def test_result_document_records_models_judge_prompt_and_temperature(tmp_path):
    from outage_matcher.config import AgentConfig

    path = tmp_path / "gold.jsonl"
    gold = [gold_row("q001", 1, "q", [2])]
    write_gold(gold, path)
    records = run_faithfulness.run_all(
        gold, lambda row: FakeAgent(agent_result()), FakeJudge(verdict(True))
    )
    doc = run_faithfulness.result_document(
        path, gold, corpus_mod.IndexInfo("v1", 3, 7), AgentConfig("agent-x"), "judge-y", records
    )
    cfg = doc["config"]
    assert (cfg["agent_model"], cfg["judge_model"], cfg["judge_temperature"]) == (
        "agent-x",
        "judge-y",
        0.0,
    )
    assert cfg["judge_prompt"]["user_template"] == faithfulness.JUDGE_USER_TEMPLATE
    assert doc["metrics"]["claim_support_rate"] == 1.0
    assert doc["tokens"]["judge"]["input_tokens"] == 50


def test_estimate_scales_with_the_number_of_queries():
    assert run_faithfulness.estimate_tokens(2)["agent_input"] == 2 * run_faithfulness.EST_AGENT_IN


def test_main_dry_run_prints_the_estimate_without_keys(tmp_path, capsys):
    path = tmp_path / "gold.jsonl"
    write_gold([gold_row("q001", 1, "q", [2])], path)
    assert run_faithfulness.main(["--gold", str(path), "--dry-run"]) == 0
    assert "estimated usage for 1 queries" in capsys.readouterr().out


def test_main_without_keys_stops_with_a_note(tmp_path, monkeypatch, capsys):
    from outage_matcher import cli

    path = tmp_path / "gold.jsonl"
    write_gold([gold_row("q001", 1, "q", [2])], path)
    monkeypatch.setattr(cli, "_api_key", lambda: None)
    monkeypatch.setattr(run_faithfulness.deepseek, "api_key", lambda: "k")
    assert run_faithfulness.main(["--gold", str(path), "--out", str(tmp_path / "o.json")]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
