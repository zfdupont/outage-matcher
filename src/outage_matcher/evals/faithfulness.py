"""LLM-as-judge faithfulness: is each claim of an agent answer supported by the cited chunks?"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from outage_matcher.agent.models import AgentResult
from outage_matcher.agent.tools import RetrievedChunk
from outage_matcher.evals.deepseek import (
    DeepSeekClient,
    DeepSeekError,
    InvalidReplyError,
    TokenUsage,
)

JUDGE_TEMPERATURE = 0.0
EVIDENCE_CHARS = 3000  # per chunk shown to the judge
MAX_EVIDENCE_CHARS = 15000  # all cited chunks together
JUDGE_ATTEMPTS = 2  # one retry when the verdict is not usable JSON (invalid, cut off, bad shape)
JUDGE_MAX_TOKENS = 4000

JUDGE_SYSTEM = (
    "You are a strict fact-checker for an incident-diagnosis assistant. Always answer with a "
    "single JSON object."
)
JUDGE_USER_TEMPLATE = """\
Below are the cited excerpts from public outage postmortems and an answer that cites them.

Cited excerpts:
{excerpts}

Answer to check:
Likely cause: {likely_cause}
Suggested fix: {suggested_fix}

Task:
1. Split the answer into atomic factual claims about what happened, what caused it or what to do.
2. For each claim decide whether the cited excerpts support it. A claim is supported only if an \
excerpt states it or clearly implies it. Generic advice that no excerpt mentions is not supported. \
Do not use outside knowledge.

Return JSON: {"claims": [{"claim": "<the claim>", "supported": true or false, \
"reason": "<short quote or explanation>"}]}"""


@dataclass(frozen=True)
class Claim:
    claim: str
    supported: bool
    reason: str


@dataclass
class Judgment:
    claims: list[Claim] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


def cited_evidence(result: AgentResult) -> list[RetrievedChunk]:
    """Chunks the agent retrieved that belong to a document its answer cites.

    `result.evidence` lists the chunks the answerer saw first, so they are kept when the budget
    runs out. A chunk that does not fit is skipped; smaller later ones can still fit."""
    cited = {c.doc_id for c in result.answer.citations}
    chunks: list[RetrievedChunk] = []
    seen: set[tuple[int, str, str]] = set()
    used = 0
    for chunk in result.evidence:
        key = (chunk.doc_id, chunk.section_type, chunk.text)
        if chunk.doc_id not in cited or key in seen:
            continue
        seen.add(key)
        text = chunk.text[:EVIDENCE_CHARS]
        if used + len(text) > MAX_EVIDENCE_CHARS:
            continue
        used += len(text)
        chunks.append(RetrievedChunk(**{**chunk.__dict__, "text": text}))
    return chunks


def judge_prompt(result: AgentResult, evidence: list[RetrievedChunk]) -> str:
    excerpts = "\n\n".join(
        f"[doc {c.doc_id}] {c.title!r} (section {c.section_type})\n{c.text}" for c in evidence
    )
    return (
        JUDGE_USER_TEMPLATE.replace("{excerpts}", excerpts or "(none)")
        .replace("{likely_cause}", result.answer.likely_cause)
        .replace("{suggested_fix}", result.answer.suggested_fix)
    )


def parse_claims(data: dict[str, Any]) -> list[Claim]:
    raw = data.get("claims")
    if not isinstance(raw, list) or not raw:
        raise ValueError("verdict has no claims list")
    claims = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("supported"), bool):
            raise ValueError("each claim needs a boolean `supported`")
        text, reason = item.get("claim"), item.get("reason")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each claim needs text")
        claims.append(
            Claim(text.strip(), item["supported"], reason if isinstance(reason, str) else "")
        )
    return claims


def judge_answer(client: DeepSeekClient, result: AgentResult) -> Judgment:
    """Judge one answer against its cited chunks. Raises DeepSeekError when no usable verdict."""
    evidence = cited_evidence(result)
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": judge_prompt(result, evidence)},
    ]
    usage = TokenUsage()
    problem = ""
    for _attempt in range(JUDGE_ATTEMPTS):
        try:
            reply = client.chat_json(
                messages, temperature=JUDGE_TEMPERATURE, max_tokens=JUDGE_MAX_TOKENS
            )
        except InvalidReplyError as exc:  # transport failures were already retried by the client
            usage = usage.plus(exc.usage)
            problem = str(exc)
            continue
        usage = usage.plus(reply.usage)
        try:
            return Judgment(parse_claims(reply.data), usage)
        except ValueError as exc:
            problem = str(exc)
    raise DeepSeekError(f"judge gave no usable verdict ({problem})")


def summarize(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-query records. Answers that abstained or errored are counted, not scored."""
    judged = [q for q in per_query if q.get("claims")]
    total = sum(len(q["claims"]) for q in judged)
    supported = sum(c["supported"] for q in judged for c in q["claims"])
    fully = sum(all(c["supported"] for c in q["claims"]) for q in judged)
    return {
        "queries": len(per_query),
        "answered_and_judged": len(judged),
        "no_match": sum(1 for q in per_query if q.get("no_match")),
        "errors": sum(1 for q in per_query if q.get("error")),
        "claims": total,
        "claims_supported": supported,
        "claim_support_rate": supported / total if total else None,
        "faithful_answer_rate": fully / len(judged) if judged else None,
    }
