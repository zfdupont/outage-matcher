"""Chunk the collected corpus, embed with both models, and write it to Postgres."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from pgvector import Vector

from outage_matcher.db import EMBEDDING_COLUMNS
from outage_matcher.ingest.chunk import Chunk, chunk_html
from outage_matcher.ingest.collect import RAW_DIR, ManifestEntry
from outage_matcher.ingest.embed import BATCH_SIZE, Embedder, get_embedder


@dataclass(frozen=True)
class PreparedDoc:
    entry: ManifestEntry
    chunks: list[Chunk]


@dataclass
class IndexResult:
    documents: int = 0
    chunks: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


def prepare_documents(
    entries: list[ManifestEntry], raw_dir: Path = RAW_DIR
) -> tuple[list[PreparedDoc], list[dict[str, str]]]:
    """Chunk each stored page. Documents with no raw file or no usable text are failures."""
    docs: list[PreparedDoc] = []
    failures: list[dict[str, str]] = []
    for entry in entries:
        path = raw_dir / f"{entry.doc_id}.html"
        if not path.exists():
            failures.append({"url": entry.url, "reason": "raw file missing"})
            continue
        chunks = chunk_html(path.read_text(encoding="utf-8", errors="replace"))
        if not chunks:
            failures.append({"url": entry.url, "reason": "no chunks extracted"})
            continue
        docs.append(PreparedDoc(entry, chunks))
    return docs, failures


def embed_all(
    texts: list[str], embedder: Embedder, batch_size: int = BATCH_SIZE
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(embedder.embed_documents(texts[start : start + batch_size]))
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedder returned {len(vectors)} vectors for {len(texts)} texts")
    return vectors


def write_index(
    conn: psycopg.Connection,
    docs: list[PreparedDoc],
    embedders: Mapping[str, Embedder] | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> IndexResult:
    """Replace the index contents with `docs`, writing one embedding column per model."""
    embedders = embedders or {key: get_embedder(key) for key in EMBEDDING_COLUMNS}
    all_chunks = [(doc, chunk) for doc in docs for chunk in doc.chunks]
    texts = [chunk.text for _doc, chunk in all_chunks]
    vectors: dict[str, list[list[float]]] = {}
    for key in EMBEDDING_COLUMNS:
        log(f"embedding {len(texts)} chunks with {key}")
        vectors[key] = embed_all(texts, embedders[key])

    with conn.transaction():
        conn.execute("TRUNCATE chunks, postmortems RESTART IDENTITY CASCADE")
        ids: dict[str, int] = {}
        for doc in docs:
            e = doc.entry
            row = conn.execute(
                "INSERT INTO postmortems (url, title, source, system_type, fetched_date) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (e.url, e.title, e.source, e.system_type, e.fetched_date),
            ).fetchone()
            ids[e.url] = row[0]
        columns = ", ".join(EMBEDDING_COLUMNS.values())
        placeholders = ", ".join(["%s"] * len(EMBEDDING_COLUMNS))
        sql = (
            f"INSERT INTO chunks (postmortem_id, ord, section_type, text, {columns}) "
            f"VALUES (%s, %s, %s, %s, {placeholders})"
        )
        for i, (doc, chunk) in enumerate(all_chunks):
            params = [ids[doc.entry.url], chunk.ord, chunk.section_type, chunk.text]
            params += [Vector(vectors[key][i]) for key in EMBEDDING_COLUMNS]
            conn.execute(sql, params)
    return IndexResult(documents=len(docs), chunks=len(all_chunks))
