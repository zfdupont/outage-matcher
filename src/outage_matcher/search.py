"""Vector search over the indexed chunks."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from pgvector import Vector

from outage_matcher.db import EMBEDDING_COLUMNS
from outage_matcher.ingest.embed import Embedder, get_embedder


@dataclass(frozen=True)
class SearchHit:
    title: str
    section_type: str
    score: float  # cosine similarity, higher is closer
    url: str
    system_type: str
    text: str


def search(
    conn: psycopg.Connection,
    query: str,
    model: str = "bge",
    k: int = 5,
    *,
    system_type: str | None = None,
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    """Top-k chunks by cosine similarity for one model, optionally within one system type."""
    if model not in EMBEDDING_COLUMNS:
        raise ValueError(f"unknown model {model!r}; choose from {sorted(EMBEDDING_COLUMNS)}")
    if k < 1:
        raise ValueError("k must be at least 1")
    column = EMBEDDING_COLUMNS[model]
    vector = Vector((embedder or get_embedder(model)).embed_query(query))
    where = "WHERE p.system_type = %s" if system_type else ""
    params: list[object] = [vector]
    if system_type:
        params.append(system_type)
    params += [vector, k]
    rows = conn.execute(
        f"SELECT p.title, c.section_type, 1 - (c.{column} <=> %s) AS score, p.url, "
        f"p.system_type, c.text FROM chunks c JOIN postmortems p ON p.id = c.postmortem_id "
        f"{where} ORDER BY c.{column} <=> %s LIMIT %s",
        params,
    ).fetchall()
    return [SearchHit(*row) for row in rows]
