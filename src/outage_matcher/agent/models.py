"""Result types of an agent run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NO_MATCH_CAUSE = "No close match found in the indexed postmortems for this incident."
NO_MATCH_FIX = (
    "Add more detail (symptoms, affected components, recent changes) and ask again, "
    "or check the incident against sources outside the index."
)


@dataclass(frozen=True)
class Citation:
    doc_id: int
    title: str
    url: str
    section: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0

    def plus(self, input_tokens: int, output_tokens: int) -> Usage:
        return Usage(
            self.input_tokens + input_tokens, self.output_tokens + output_tokens, self.llm_calls + 1
        )


@dataclass(frozen=True)
class AgentAnswer:
    likely_cause: str
    suggested_fix: str
    citations: list[Citation] = field(default_factory=list)
    no_match: bool = False
    notes: list[str] = field(default_factory=list)  # for example dropped invalid citations


@dataclass(frozen=True)
class AgentResult:
    question: str
    answer: AgentAnswer
    usage: Usage
    retries: int
    events: list[dict[str, Any]]  # ordered trace of tool calls, grades, rewrites
