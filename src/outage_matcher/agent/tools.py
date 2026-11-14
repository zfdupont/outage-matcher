"""Agent tools over the postmortem index: JSON-schema definitions and implementations.

Every tool returns a `ToolResult`; failures (bad arguments, unknown tools, database or embedding
errors) become structured error results and never raise into the agent loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from outage_matcher.ingest.embed import Embedder
from outage_matcher.search import search as search_chunks

BACKEND_ERROR = "tool_failed"  # error type for database or embedding failures, not model mistakes
DEFAULT_K = 5
MAX_TOOL_K = 20
SNIPPET_CHARS = 800  # chunk text shown to the model per search hit
DOCUMENT_CHARS = 6000  # cap on a whole postmortem returned by get_postmortem
LIST_LIMIT = 25  # documents listed by filter_by_system_type without a query


@dataclass(frozen=True)
class RetrievedChunk:
    """A piece of evidence the agent has seen. Citations may only reference its doc_id."""

    doc_id: int
    title: str
    url: str
    section_type: str
    system_type: str
    text: str
    score: float | None = None


@dataclass
class ToolResult:
    content: dict[str, Any]  # JSON-serializable payload sent back to the model
    is_error: bool = False
    retrieved: list[RetrievedChunk] = field(default_factory=list)


@dataclass
class ToolContext:
    conn: Any  # psycopg.Connection (tests pass a fake)
    embedding_model: str = "bge"
    embedder: Embedder | None = None


class ToolArgumentError(ValueError):
    pass


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_incidents",
        "description": (
            "Semantic search over indexed public outage postmortems. Returns the most similar "
            "chunks with doc_id, title, url, section type and text. Describe symptoms, affected "
            "components and triggers rather than guessing the cause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language incident query."},
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_TOOL_K,
                    "description": f"Number of chunks to return (default {DEFAULT_K}).",
                },
                "system_type": {
                    "type": "string",
                    "description": "Optional system type label to restrict the search.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_postmortem",
        "description": (
            "Fetch the full indexed text of one postmortem by doc_id, as returned by a search. "
            "Use it to read root cause and remediation sections of a promising match."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"doc_id": {"type": "integer", "description": "Postmortem doc id."}},
            "required": ["doc_id"],
        },
    },
    {
        "name": "filter_by_system_type",
        "description": (
            "Restrict to one system type (for example database, network, storage). With a query, "
            "searches only within that type; without a query, lists documents of that type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "system_type": {"type": "string", "description": "System type label."},
                "query": {"type": "string", "description": "Optional search query."},
            },
            "required": ["system_type"],
        },
    },
]


def _error(kind: str, message: str) -> ToolResult:
    return ToolResult({"error": {"type": kind, "message": message}}, is_error=True)


def _text_arg(args: dict[str, Any], name: str, *, required: bool) -> str | None:
    value = args.get(name)
    if value is None:
        if required:
            raise ToolArgumentError(f"missing required argument {name!r}")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError(f"argument {name!r} must be a non-empty string")
    return value.strip()


def _int_arg(
    args: dict[str, Any], name: str, *, required: bool, default: int | None = None
) -> int | None:
    value = args.get(name)
    if value is None:
        if required:
            raise ToolArgumentError(f"missing required argument {name!r}")
        return default
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(f"argument {name!r} must be an integer")
    return value


def _chunk_payload(chunk: RetrievedChunk) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "url": chunk.url,
        "section": chunk.section_type,
        "system_type": chunk.system_type,
        "text": chunk.text[:SNIPPET_CHARS],
    }
    if chunk.score is not None:
        payload["score"] = round(chunk.score, 3)
    return payload


def known_system_types(conn: Any) -> list[str]:
    rows = conn.execute("SELECT DISTINCT system_type FROM postmortems ORDER BY 1").fetchall()
    return [row[0] for row in rows]


def _run_search(ctx: ToolContext, query: str, k: int, system_type: str | None) -> ToolResult:
    if not 1 <= k <= MAX_TOOL_K:
        raise ToolArgumentError(f"argument 'k' must be between 1 and {MAX_TOOL_K}")
    if system_type is not None:
        known = known_system_types(ctx.conn)
        if system_type not in known:
            return _error(
                "unknown_system_type", f"unknown system_type {system_type!r}; valid: {known}"
            )
    hits = search_chunks(
        ctx.conn, query, ctx.embedding_model, k, system_type=system_type, embedder=ctx.embedder
    )
    chunks = [
        RetrievedChunk(
            h.postmortem_id, h.title, h.url, h.section_type, h.system_type, h.text, h.score
        )
        for h in hits
    ]
    return ToolResult(
        {"count": len(chunks), "results": [_chunk_payload(c) for c in chunks]}, retrieved=chunks
    )


def search_incidents(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    query = _text_arg(args, "query", required=True)
    k = _int_arg(args, "k", required=False, default=DEFAULT_K)
    system_type = _text_arg(args, "system_type", required=False)
    assert query is not None and k is not None
    return _run_search(ctx, query, k, system_type)


def get_postmortem(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    doc_id = _int_arg(args, "doc_id", required=True)
    meta = ctx.conn.execute(
        "SELECT title, url, system_type FROM postmortems WHERE id = %s", (doc_id,)
    ).fetchone()
    if meta is None:
        return _error("not_found", f"no postmortem with doc_id {doc_id}")
    title, url, system_type = meta
    rows = ctx.conn.execute(
        "SELECT section_type, text FROM chunks WHERE postmortem_id = %s ORDER BY ord", (doc_id,)
    ).fetchall()
    parts: list[str] = []
    used = 0
    for section_type, text in rows:
        if used >= DOCUMENT_CHARS:
            break
        piece = f"[{section_type}] {text}"[: DOCUMENT_CHARS - used]
        parts.append(piece)
        used += len(piece)
    full_text = "\n\n".join(parts)
    chunk = RetrievedChunk(doc_id, title, url, "full_document", system_type, full_text)
    assert doc_id is not None
    return ToolResult(
        {
            "doc_id": doc_id,
            "title": title,
            "url": url,
            "system_type": system_type,
            "text": full_text,
            "truncated": used >= DOCUMENT_CHARS and len(rows) > len(parts),
        },
        retrieved=[chunk],
    )


def filter_by_system_type(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    system_type = _text_arg(args, "system_type", required=True)
    query = _text_arg(args, "query", required=False)
    assert system_type is not None
    if query:
        return _run_search(ctx, query, DEFAULT_K, system_type)
    known = known_system_types(ctx.conn)
    if system_type not in known:
        return _error("unknown_system_type", f"unknown system_type {system_type!r}; valid: {known}")
    rows = ctx.conn.execute(
        "SELECT id, title, url FROM postmortems WHERE system_type = %s ORDER BY id LIMIT %s",
        (system_type, LIST_LIMIT),
    ).fetchall()
    docs = [{"doc_id": r[0], "title": r[1], "url": r[2]} for r in rows]
    return ToolResult({"system_type": system_type, "count": len(docs), "documents": docs})


TOOLS: dict[str, Callable[[ToolContext, dict[str, Any]], ToolResult]] = {
    "search_incidents": search_incidents,
    "get_postmortem": get_postmortem,
    "filter_by_system_type": filter_by_system_type,
}


def run_tool(ctx: ToolContext, name: str, args: Any) -> ToolResult:
    """Dispatch one tool call. Never raises: problems come back as error results."""
    handler = TOOLS.get(name)
    if handler is None:
        return _error("unknown_tool", f"unknown tool {name!r}; available: {sorted(TOOLS)}")
    if not isinstance(args, dict):
        return _error("invalid_arguments", "tool arguments must be a JSON object")
    try:
        result = handler(ctx, args)
    except ToolArgumentError as exc:
        _end_transaction(ctx.conn, ok=True)
        return _error("invalid_arguments", str(exc))
    except Exception as exc:  # the agent loop must survive any tool failure
        _end_transaction(ctx.conn, ok=False)
        return _error(BACKEND_ERROR, f"{type(exc).__name__}: {exc}")
    _end_transaction(ctx.conn, ok=True)
    return result


def _end_transaction(conn: Any, *, ok: bool) -> None:
    """Close the implicit transaction so a failed query or SET LOCAL cannot leak into the next."""
    end = getattr(conn, "commit" if ok else "rollback", None)
    if end is None:
        return
    try:
        end()
    except psycopg.Error:
        pass
