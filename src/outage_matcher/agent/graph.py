"""LangGraph agent: retrieve (tool use), grade, rewrite and retry, answer with citations."""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from outage_matcher.agent.models import (
    NO_MATCH_CAUSE,
    NO_MATCH_FIX,
    AgentAnswer,
    AgentResult,
    Citation,
    RetrievalError,
    Usage,
)
from outage_matcher.agent.tools import (
    BACKEND_ERROR,
    TOOL_DEFINITIONS,
    RetrievedChunk,
    ToolContext,
    run_tool,
)
from outage_matcher.config import AgentConfig

MAX_TOOL_TURNS = 4  # model calls inside one retrieve node
GRADE_CHARS = 700  # chunk text shown to the grader
ANSWER_CHARS = 1500  # chunk text shown to the answerer
MAX_ANSWER_CHUNKS = 8

RETRIEVE_SYSTEM = (
    "You are an SRE assistant that finds past public outage postmortems similar to a new "
    "incident. Use the tools to search the index: call search_incidents with a symptom-focused "
    "query (and system_type when the affected system is clear), and get_postmortem to read a "
    "promising match. Make one to three tool calls, then reply with one short sentence. "
    "Do not diagnose the incident yourself."
)
GRADE_SYSTEM = (
    "You grade retrieved postmortem excerpts for relevance to an incident. An excerpt is "
    "relevant only if it describes a similar failure (comparable symptoms, trigger or component) "
    "that would help diagnose or fix the incident. Shared keywords alone are not enough. "
    "Call submit_grades with one entry per excerpt."
)
REWRITE_SYSTEM = (
    "You rewrite a failed search query for a postmortem index. Use different vocabulary: name "
    "likely components, failure modes or triggers instead of repeating earlier wording. "
    "Call submit_query with the new query."
)
ANSWER_SYSTEM = (
    "You are an SRE assistant. Using only the numbered excerpts, state the most likely cause of "
    "the incident and a suggested fix, and say so if the excerpts only partly cover it. "
    "Cite the doc_id of every excerpt you relied on and no others. Call submit_answer."
)

GRADE_TOOL = {
    "name": "submit_grades",
    "description": "Relevance verdict for each numbered excerpt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "grades": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "relevant": {"type": "boolean"},
                    },
                    "required": ["index", "relevant"],
                },
            }
        },
        "required": ["grades"],
    },
}
REWRITE_TOOL = {
    "name": "submit_query",
    "description": "The rewritten search query.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}
ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Final diagnosis with citations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "likely_cause": {"type": "string"},
            "suggested_fix": {"type": "string"},
            "citations": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "doc_ids of the excerpts relied on.",
            },
        },
        "required": ["likely_cause", "suggested_fix", "citations"],
    },
}


class AgentState(TypedDict):
    question: str
    query: str  # current search query (the question on the first pass)
    past_queries: list[str]
    retries: int
    pending: list[RetrievedChunk]  # retrieved by the latest retrieve node, awaiting grading
    retrieved: list[RetrievedChunk]  # everything retrieved so far (citable)
    relevant: list[RetrievedChunk]  # chunks the grader accepted
    usage: Usage
    events: list[dict[str, Any]]
    answer: AgentAnswer | None


def _echo_blocks(content: list[Any]) -> list[dict[str, Any]]:
    """Assistant blocks to send back. The API rejects empty text blocks, so those are skipped."""
    blocks: list[dict[str, Any]] = []
    for block in content:
        if block.type == "tool_use":
            blocks.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
        elif (getattr(block, "text", "") or "").strip():
            blocks.append({"type": "text", "text": block.text})
    return blocks


def _chunk_key(chunk: RetrievedChunk) -> tuple[int, str, str]:
    return (chunk.doc_id, chunk.section_type, chunk.text)


def _merge(existing: list[RetrievedChunk], new: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen = {_chunk_key(c) for c in existing}
    merged = list(existing)
    for chunk in new:
        if _chunk_key(chunk) not in seen:
            seen.add(_chunk_key(chunk))
            merged.append(chunk)
    return merged


def _excerpts(chunks: list[RetrievedChunk], limit: int) -> str:
    return "\n\n".join(
        f"[{i}] doc_id={c.doc_id} title={c.title!r} section={c.section_type}\n{c.text[:limit]}"
        for i, c in enumerate(chunks)
    )


class OutageAgent:
    """Holds the Anthropic client, tool context and config; `graph` is the compiled workflow."""

    def __init__(self, client: Any, ctx: ToolContext, config: AgentConfig) -> None:
        self.client = client
        self.ctx = ctx
        self.config = config
        self.graph = self._build()

    # ----- LLM plumbing -------------------------------------------------------------------

    def _call(self, usage: Usage, max_tokens: int, **kwargs: Any) -> tuple[Any, Usage]:
        response = self.client.messages.create(
            model=self.config.model, max_tokens=max_tokens, **kwargs
        )
        used = getattr(response, "usage", None)
        usage = usage.plus(
            getattr(used, "input_tokens", 0) or 0, getattr(used, "output_tokens", 0) or 0
        )
        return response, usage

    def _forced(
        self, usage: Usage, system: str, tool: dict[str, Any], prompt: str, max_tokens: int
    ) -> tuple[dict[str, Any] | None, Usage]:
        """Structured output: force one tool and return its input (None if malformed)."""
        response, usage = self._call(
            usage,
            max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return (block.input if isinstance(block.input, dict) else None), usage
        return None, usage

    # ----- nodes --------------------------------------------------------------------------

    def retrieve(self, state: AgentState) -> dict[str, Any]:
        prompt = f"Incident: {state['question']}\n\nSearch focus: {state['query']}"
        if state["past_queries"]:
            prompt += "\nQueries that already found nothing useful: " + "; ".join(
                state["past_queries"]
            )
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        usage, events = state["usage"], list(state["events"])
        found: list[RetrievedChunk] = []
        backend_failures: list[str] = []
        for _turn in range(MAX_TOOL_TURNS):
            response, usage = self._call(
                usage,
                1024,
                system=RETRIEVE_SYSTEM,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                break
            messages.append({"role": "assistant", "content": _echo_blocks(response.content)})
            results = []
            for call in calls:
                result = run_tool(self.ctx, call.name, call.input)
                found = _merge(found, result.retrieved)
                error = result.content.get("error") or {}
                if error.get("type") == BACKEND_ERROR:
                    backend_failures.append(error.get("message", "unknown error"))
                events.append(
                    {
                        "type": "tool_call",
                        "name": call.name,
                        "input": call.input,
                        "is_error": result.is_error,
                        "doc_ids": sorted({c.doc_id for c in result.retrieved}),
                        "error": result.content.get("error"),
                    }
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(result.content),
                        "is_error": result.is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
        if backend_failures and not found:
            # The search never ran properly; reporting "no close match" would mislead the user.
            raise RetrievalError(
                f"search failed: {backend_failures[0]}; this is not a no-match result"
            )
        return {
            "pending": found,
            "retrieved": _merge(state["retrieved"], found),
            "usage": usage,
            "events": events,
        }

    def grade(self, state: AgentState) -> dict[str, Any]:
        pending = state["pending"]
        events = list(state["events"])
        if not pending:
            events.append({"type": "grade", "graded": 0, "relevant": 0})
            return {"events": events}
        prompt = f"Incident: {state['question']}\n\nExcerpts:\n{_excerpts(pending, GRADE_CHARS)}"
        data, usage = self._forced(state["usage"], GRADE_SYSTEM, GRADE_TOOL, prompt, 1024)
        accepted: set[int] = set()
        grades = data.get("grades") if data else None
        for item in grades if isinstance(grades, list) else []:
            index = item.get("index") if isinstance(item, dict) else None
            if (
                isinstance(index, int)
                and not isinstance(index, bool)
                and 0 <= index < len(pending)
                and item.get("relevant") is True
            ):
                accepted.add(index)
        relevant = [c for i, c in enumerate(pending) if i in accepted]
        events.append(
            {
                "type": "grade",
                "graded": len(pending),
                "relevant": len(relevant),
                "malformed": not isinstance(grades, list),
            }
        )
        return {
            "relevant": _merge(state["relevant"], relevant),
            "usage": usage,
            "events": events,
        }

    def route(self, state: AgentState) -> Literal["rewrite", "answer"]:
        if state["relevant"] or state["retries"] >= self.config.max_retries:
            return "answer"
        return "rewrite"

    def rewrite(self, state: AgentState) -> dict[str, Any]:
        titles = "; ".join(sorted({c.title for c in state["retrieved"]})[:8]) or "none"
        prompt = (
            f"Incident: {state['question']}\n"
            f"Failed queries: {'; '.join(state['past_queries'] + [state['query']])}\n"
            f"Irrelevant titles that came back: {titles}"
        )
        data, usage = self._forced(state["usage"], REWRITE_SYSTEM, REWRITE_TOOL, prompt, 256)
        new_query = data.get("query") if data else None
        if not isinstance(new_query, str) or not new_query.strip():
            new_query = state["question"]  # malformed rewrite: fall back, the retry still counts
        events = [*state["events"], {"type": "rewrite", "query": new_query.strip()}]
        return {
            "query": new_query.strip(),
            "past_queries": [*state["past_queries"], state["query"]],
            "retries": state["retries"] + 1,
            "usage": usage,
            "events": events,
        }

    def answer(self, state: AgentState) -> dict[str, Any]:
        relevant = state["relevant"][:MAX_ANSWER_CHUNKS]
        if not relevant:
            return {"answer": AgentAnswer(NO_MATCH_CAUSE, NO_MATCH_FIX, no_match=True)}
        prompt = f"Incident: {state['question']}\n\nExcerpts:\n{_excerpts(relevant, ANSWER_CHARS)}"
        data, usage = self._forced(state["usage"], ANSWER_SYSTEM, ANSWER_TOOL, prompt, 1500)
        answer = self._validated_answer(data, state["retrieved"], relevant)
        return {"answer": answer, "usage": usage}

    def _validated_answer(
        self,
        data: dict[str, Any] | None,
        retrieved: list[RetrievedChunk],
        relevant: list[RetrievedChunk],
    ) -> AgentAnswer:
        """Keep only citations of retrieved docs. No valid citation means no grounded answer."""
        if not data:
            return AgentAnswer(
                NO_MATCH_CAUSE, NO_MATCH_FIX, no_match=True, notes=["malformed answer from model"]
            )
        by_doc: dict[int, RetrievedChunk] = {}
        for chunk in [*relevant, *retrieved]:  # prefer the chunk the grader accepted
            by_doc.setdefault(chunk.doc_id, chunk)
        citations: list[Citation] = []
        dropped: list[Any] = []
        raw = data.get("citations")
        for value in raw if isinstance(raw, list) else []:
            if isinstance(value, str) and value.strip().isdigit():
                value = int(value.strip())
            if isinstance(value, bool) or not isinstance(value, int) or value not in by_doc:
                dropped.append(value)
                continue
            if any(c.doc_id == value for c in citations):
                continue
            chunk = by_doc[value]
            citations.append(Citation(chunk.doc_id, chunk.title, chunk.url, chunk.section_type))
        notes = [f"dropped citation of a document that was not retrieved: {d!r}" for d in dropped]
        cause, fix = data.get("likely_cause"), data.get("suggested_fix")
        if not citations or not isinstance(cause, str) or not isinstance(fix, str):
            notes.append("answer had no valid citations or text; returning no match")
            return AgentAnswer(NO_MATCH_CAUSE, NO_MATCH_FIX, no_match=True, notes=notes)
        return AgentAnswer(cause.strip(), fix.strip(), citations, notes=notes)

    # ----- graph --------------------------------------------------------------------------

    def _build(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("retrieve", self.retrieve)
        graph.add_node("grade", self.grade)
        graph.add_node("rewrite", self.rewrite)
        graph.add_node("answer", self.answer)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_conditional_edges("grade", self.route, {"rewrite": "rewrite", "answer": "answer"})
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("answer", END)
        return graph.compile()

    def ask(self, question: str) -> AgentResult:
        state: AgentState = {
            "question": question,
            "query": question,
            "past_queries": [],
            "retries": 0,
            "pending": [],
            "retrieved": [],
            "relevant": [],
            "usage": Usage(),
            "events": [],
            "answer": None,
        }
        # Each pass is retrieve, grade, rewrite; the hard cap is max_retries, this only guards bugs.
        limit = 8 + 3 * (self.config.max_retries + 1)
        final = self.graph.invoke(state, {"recursion_limit": limit})
        answer = final["answer"]
        assert answer is not None
        # Evidence for the evals: the excerpts the answerer saw first, then everything else.
        evidence = _merge(final["relevant"][:MAX_ANSWER_CHUNKS], final["retrieved"])
        return AgentResult(
            question, answer, final["usage"], final["retries"], final["events"], evidence
        )
