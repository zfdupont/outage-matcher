"""Adapter from the LangGraph agent to the API's `Agent` protocol.

Each request opens its own database connection (psycopg connections are not shared across the
threads FastAPI runs sync endpoints on) and builds the agent around it; the Anthropic client and
the embedding model are shared and thread safe.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from outage_matcher import db
from outage_matcher.agent.models import AgentResult
from outage_matcher.api.models import AskResponse, Citation


def to_response(result: AgentResult) -> AskResponse:
    answer = result.answer
    return AskResponse(
        answer=f"Likely cause: {answer.likely_cause}\nSuggested fix: {answer.suggested_fix}",
        likely_cause=answer.likely_cause,
        suggested_fix=answer.suggested_fix,
        citations=[
            Citation(doc_id=str(c.doc_id), title=c.title, url=c.url, section=c.section)
            for c in answer.citations
        ],
    )


def open_connection() -> AbstractContextManager[Any]:
    # The schema is created by `outage-matcher ingest`; do not run DDL on every request.
    return db.connect(ensure_schema=False)


class ApiAgent:
    """`build(conn)` returns an object with `ask(question) -> AgentResult` bound to `conn`."""

    def __init__(
        self,
        build: Callable[[Any], Any],
        connect: Callable[[], AbstractContextManager[Any]] | None = None,
    ) -> None:
        self._build = build
        self._connect = connect

    def ask(self, question: str) -> AskResponse:
        with (self._connect or open_connection)() as conn:
            result = self._build(conn).ask(question)
        return to_response(result)
