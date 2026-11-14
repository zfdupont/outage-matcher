import json

import pytest

from outage_matcher.evals import build_gold, gold
from outage_matcher.evals.corpus import ChunkRow, DocRow
from outage_matcher.evals.deepseek import ChatResult, DeepSeekError, TokenUsage

ROOT = (
    "Root cause\nA regular expression with catastrophic backtracking was deployed to the "
    "web application firewall rules and consumed every CPU core on the edge machines. "
) * 2
SYMPTOMS = [
    "Summary\nCustomers saw errors and slow pages for about thirty minutes on Tuesday. " * 6,
    "Impact\nSites returned gateway errors and dashboards would not load for many users. " * 6,
]


def make_doc(doc_id=1, title="Edge outage", url="https://blog.examplecdn.test/a", root=ROOT):
    chunks = [ChunkRow(10 * doc_id, 0, "summary", SYMPTOMS[0])]
    chunks.append(ChunkRow(10 * doc_id + 1, 1, "impact", SYMPTOMS[1]))
    chunks.append(ChunkRow(10 * doc_id + 2, 2, "root_cause", root))
    return DocRow(doc_id, url, title, "community", "network", tuple(chunks))


class FakeDeepSeek:
    """Scripted chat_json: each call pops the next reply (a dict or an exception)."""

    model = "deepseek-flash"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat_json(self, messages, *, temperature=0.0, max_tokens=1024):
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(reply, json.dumps(reply), TokenUsage(100, 20, 1))


GOOD = "Pages keep failing with gateway errors and the dashboard will not load for most users."


def usable(query=GOOD, notes="described errors"):
    return {"usable": True, "query": query, "notes": notes}


def no_candidates(query, doc):
    return []


def test_eligibility_needs_root_cause_text_and_remaining_chunks():
    assert gold.is_eligible(make_doc())
    assert not gold.is_eligible(make_doc(root="Root cause\nshort"))
    assert not gold.is_eligible(make_doc(title="GitHub availability report: May 2026"))
    only_root = DocRow(1, "https://a.test", "T", "s", "x", (ChunkRow(1, 0, "root_cause", ROOT),))
    assert not gold.is_eligible(only_root)


def test_select_candidates_is_deterministic_and_skips_ineligible():
    docs = [make_doc(i) for i in range(1, 9)] + [make_doc(99, root="Root cause\nshort")]
    first = [d.id for d in gold.select_candidates(docs, seed=3)]
    assert first == [d.id for d in gold.select_candidates(docs, seed=3)]
    assert sorted(first) == list(range(1, 9))
    assert first != [d.id for d in gold.select_candidates(docs, seed=4)]


@pytest.mark.parametrize(
    "query, fragment",
    [
        ("too short", "length"),
        (
            "a regular expression with catastrophic backtracking was deployed so users saw errors",
            "root-cause",
        ),
        ("Customers saw errors and slow pages for about thirty minutes on Tuesday", "postmortem"),
        ("The examplecdn network is returning gateway errors for most of our users", "names"),
        ("We are still looking for the root cause of the gateway errors users see", "root cause"),
    ],
)
def test_leak_problems_flags_each_kind_of_leak(query, fragment):
    assert any(fragment in p for p in gold.leak_problems(query, make_doc()))


def test_leak_problems_accepts_a_clean_query():
    assert gold.leak_problems(GOOD, make_doc()) == []


def test_shares_run_needs_consecutive_words():
    text = "a b c d e f".split()
    assert gold.shares_run("x c d e y".split(), text, 3)
    assert not gold.shares_run("c x d e".split(), text, 3)
    assert not gold.shares_run("c d".split(), text, 3)


def test_prompt_shows_symptoms_and_root_cause_to_the_model_but_asks_to_hide_it():
    prompt = gold.query_prompt(make_doc())
    assert "gateway errors" in prompt
    assert "catastrophic backtracking" in prompt
    assert "never reveal" in prompt


def test_draft_query_retries_after_a_leaky_reply_and_feeds_back_the_problems():
    leaky = usable("A regular expression with catastrophic backtracking made pages fail at scale")
    client = FakeDeepSeek(leaky, usable())
    stats = build_gold.BuildStats()
    drafted = build_gold.draft_query(client, make_doc(), stats, temperature=0.2, max_attempts=3)
    assert drafted is not None
    query, notes = drafted
    assert query == GOOD
    assert "attempt 2 of 3" in notes
    retry_message = client.calls[1][-1]["content"]
    assert "rejected" in retry_message and "root-cause" in retry_message
    assert stats.usage.calls == 2


def test_draft_query_gives_up_after_max_attempts():
    leaky = usable("short")
    stats = build_gold.BuildStats()
    assert (
        build_gold.draft_query(
            FakeDeepSeek(leaky, leaky), make_doc(), stats, temperature=0.2, max_attempts=2
        )
        is None
    )
    assert stats.leaky == 1


def test_draft_query_skips_documents_the_model_calls_unusable():
    stats = build_gold.BuildStats()
    client = FakeDeepSeek({"usable": False, "query": "", "notes": "digest"})
    assert (
        build_gold.draft_query(client, make_doc(), stats, temperature=0.2, max_attempts=3) is None
    )
    assert stats.unusable == 1


def test_parse_near_duplicates_keeps_valid_unique_suggestions_unconfirmed():
    cands = [
        gold.NearDupCandidate(5, "Same outage, other outlet", "https://b.test", "text"),
        gold.NearDupCandidate(6, "Unrelated", "https://c.test", "text"),
    ]
    data = {
        "same_incident": [
            {"index": 0, "reason": "same date and provider"},
            {"index": 0, "reason": "again"},
            {"index": 7, "reason": "out of range"},
            {"index": True, "reason": "bool"},
            "garbage",
        ]
    }
    found = gold.parse_near_duplicates(data, cands)
    assert [(n.doc_id, n.confirmed, n.reason) for n in found] == [
        (5, False, "same date and provider")
    ]
    assert gold.parse_near_duplicates({"same_incident": "none"}, cands) == []


def test_relevant_doc_ids_count_only_confirmed_near_duplicates():
    row = build_row()
    row.near_duplicates = [
        gold.NearDuplicate(5, "t", "u", "r", confirmed=True),
        gold.NearDuplicate(6, "t", "u", "r"),
    ]
    assert row.relevant_doc_ids == [row.doc_id, 5]


def build_row():
    rows, _ = build_gold.build_gold(
        [make_doc(1)], FakeDeepSeek(usable()), no_candidates, index_version="abc", count=1
    )
    return rows[0]


def test_build_gold_records_doc_held_out_section_and_generation(tmp_path):
    cands = [gold.NearDupCandidate(2, "Mirror", "https://m.test", "mirror text")]
    client = FakeDeepSeek(usable(), {"same_incident": [{"index": 0, "reason": "same outage"}]})
    docs = [make_doc(1), make_doc(2)]
    rows, stats = build_gold.build_gold(
        docs,
        client,
        lambda q, d: cands,
        index_version="abc123",
        count=1,
        seed=0,
        today=__import__("datetime").date(2026, 11, 14),
    )
    assert len(rows) == 1 and stats.attempted == 1
    row = rows[0]
    doc = docs[row.doc_id - 1]
    assert row.id == "q001" and row.query == GOOD
    assert row.held_out_chunk_id == doc.root_cause_chunks[0].id
    assert row.held_out_chunk_ids == [c.id for c in doc.root_cause_chunks]
    assert row.held_out_ords == [2]
    assert row.held_out_heading == "Root cause"
    assert row.index_version == "abc123"
    assert row.generation == {
        "model": "deepseek-flash",
        "temperature": 0.2,
        "date": "2026-11-14",
        "seed": 0,
    }
    assert [(n.doc_id, n.confirmed) for n in row.near_duplicates] == [(2, False)]

    path = tmp_path / "gold.jsonl"
    gold.write_gold(rows, path)
    assert gold.read_gold(path) == rows


def test_build_gold_skips_documents_with_api_errors_and_stops_at_count():
    docs = [make_doc(1), make_doc(2), make_doc(3)]
    client = FakeDeepSeek(DeepSeekError("boom"), usable(), {}, usable(), {})
    one = [gold.NearDupCandidate(9, "Other", "https://o.test", "text")]
    rows, stats = build_gold.build_gold(
        docs, client, lambda q, d: one, index_version="v", count=2, seed=0
    )
    assert len(rows) == 2
    assert [r.id for r in rows] == ["q001", "q002"]
    assert stats.errors == 1 and stats.attempted == 3


def test_read_gold_missing_file_has_a_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_gold"):
        gold.read_gold(tmp_path / "none.jsonl")


def test_main_without_key_exits_with_a_note(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(build_gold.deepseek, "api_key", lambda: None)
    assert build_gold.main(["--out", str(tmp_path / "g.jsonl")]) == 1
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().err


def test_main_refuses_to_overwrite_without_force(capsys, tmp_path):
    out = tmp_path / "g.jsonl"
    out.write_text("")
    assert build_gold.main(["--out", str(out)]) == 1
    assert "--force" in capsys.readouterr().err
