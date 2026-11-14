"""Vector search over the indexed chunks."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

import psycopg
from pgvector import Vector

from outage_matcher.db import EMBEDDING_COLUMNS
from outage_matcher.ingest.embed import Embedder, get_embedder

MAX_K = 1000  # pgvector caps hnsw.ef_search at 1000
DEFAULT_EF_SEARCH = 40


@dataclass(frozen=True)
class SearchHit:
    title: str
    section_type: str
    score: float  # cosine similarity, higher is closer
    url: str
    system_type: str
    text: str
    postmortem_id: int = 0  # postmortems.id, the doc id used for citations


def search(
    conn: psycopg.Connection,
    query: str,
    model: str = "bge",
    k: int = 5,
    *,
    system_type: str | None = None,
    exclude_chunk_ids: Collection[int] = (),
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    """Top-k chunks by cosine similarity for one model, optionally within one system type.

    `exclude_chunk_ids` hides chunks (the evals hold out a gold query's root-cause section)."""
    if model not in EMBEDDING_COLUMNS:
        raise ValueError(f"unknown model {model!r}; choose from {sorted(EMBEDDING_COLUMNS)}")
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}")
    column = EMBEDDING_COLUMNS[model]
    vector = Vector((embedder or get_embedder(model)).embed_query(query))
    conditions: list[str] = []
    params: list[object] = [vector]
    if system_type:
        conditions.append("p.system_type = %s")
        params.append(system_type)
    if exclude_chunk_ids:
        conditions.append("c.id <> ALL(%s::int[])")
        params.append(sorted(exclude_chunk_ids))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params += [vector, k]
    with conn.transaction():
        # The HNSW scan returns at most ef_search candidates, so raise it to cover k. With a
        # filter, the iterative scan keeps scanning until enough matching rows are found.
        conn.execute(f"SET LOCAL hnsw.ef_search = {max(k, DEFAULT_EF_SEARCH)}")
        if conditions:
            conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        rows = conn.execute(
            f"SELECT p.title, c.section_type, 1 - (c.{column} <=> %s) AS score, p.url, "
            f"p.system_type, c.text, p.id FROM chunks c "
            f"JOIN postmortems p ON p.id = c.postmortem_id "
            f"{where} ORDER BY c.{column} <=> %s LIMIT %s",
            params,
        ).fetchall()
    hits = [SearchHit(*row) for row in rows]
    return sorted(hits, key=lambda hit: hit.score, reverse=True)  # relaxed scans can be off
