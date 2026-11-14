"""Typed request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MAX_QUESTION_CHARS = 4000


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class Citation(BaseModel):
    doc_id: str
    title: str
    url: str
    section: str


class AskResponse(BaseModel):
    answer: str
    likely_cause: str
    suggested_fix: str
    citations: list[Citation] = Field(default_factory=list)
