"""Plain-text and Markdown rendering of an agent run."""

from __future__ import annotations

import json
from datetime import date

from outage_matcher.agent.models import AgentResult


def render_answer(result: AgentResult) -> str:
    answer = result.answer
    lines = [f"Likely cause: {answer.likely_cause}", f"Suggested fix: {answer.suggested_fix}"]
    if answer.citations:
        lines.append("Citations:")
        lines += [
            f"  [{c.doc_id}] {c.title} ({c.section})\n      {c.url}" for c in answer.citations
        ]
    else:
        lines.append("Citations: none")
    lines += [f"Note: {note}" for note in answer.notes]
    return "\n".join(lines)


def render_usage(result: AgentResult) -> str:
    u = result.usage
    return (
        f"Usage: {u.llm_calls} LLM calls, {u.input_tokens} input tokens, "
        f"{u.output_tokens} output tokens, {result.retries} query rewrites"
    )


def _render_event(event: dict) -> str:
    kind = event["type"]
    if kind == "tool_call":
        outcome = f"error {event['error']['type']}" if event["is_error"] else "ok"
        docs = f", doc_ids {event['doc_ids']}" if event["doc_ids"] else ""
        return f"- tool `{event['name']}` {json.dumps(event['input'])}: {outcome}{docs}"
    if kind == "grade":
        return f"- grade: {event['relevant']} of {event['graded']} chunks relevant"
    if kind == "rewrite":
        return f"- rewrite: {event['query']!r}"
    return f"- {kind}"


def render_markdown(result: AgentResult, model: str) -> str:
    """A saved transcript: question, every step the graph took, the answer and token usage."""
    steps = "\n".join(_render_event(e) for e in result.events) or "- none"
    return (
        f"# Agent run\n\n"
        f"- Date: {date.today().isoformat()}\n"
        f"- Model: {model}\n\n"
        f"## Question\n\n{result.question}\n\n"
        f"## Steps\n\n{steps}\n\n"
        f"## Answer\n\n```\n{render_answer(result)}\n```\n\n"
        f"{render_usage(result)}\n"
    )
