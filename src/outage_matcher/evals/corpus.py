"""Read the indexed corpus (documents and chunks) for the evals, and fingerprint the index."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class ChunkRow:
    id: int
    ord: int
    section_type: str
    text: str


@dataclass(frozen=True)
class DocRow:
    id: int
    url: str
    title: str
    source: str
    system_type: str
    chunks: tuple[ChunkRow, ...]

    def chunks_of(self, section_type: str) -> list[ChunkRow]:
        return [c for c in self.chunks if c.section_type == section_type]

    @property
    def root_cause_chunks(self) -> list[ChunkRow]:
        return self.chunks_of("root_cause")

    @property
    def other_chunks(self) -> list[ChunkRow]:
        return [c for c in self.chunks if c.section_type != "root_cause"]


@dataclass(frozen=True)
class IndexInfo:
    version: str  # hash of every document and chunk (ids, urls, order, text)
    documents: int
    chunks: int


def load_docs(conn: psycopg.Connection) -> list[DocRow]:
    """Every document with its chunks in order (no embeddings), ordered by document id."""
    docs = conn.execute(
        "SELECT id, url, title, source, system_type FROM postmortems ORDER BY id"
    ).fetchall()
    by_doc: dict[int, list[ChunkRow]] = {row[0]: [] for row in docs}
    rows = conn.execute(
        "SELECT postmortem_id, id, ord, section_type, text FROM chunks ORDER BY postmortem_id, ord"
    ).fetchall()
    for doc_id, chunk_id, ord_, section_type, text in rows:
        by_doc[doc_id].append(ChunkRow(chunk_id, ord_, section_type, text))
    return [DocRow(*row, tuple(by_doc[row[0]])) for row in docs]


def index_info(conn: psycopg.Connection) -> IndexInfo:
    """Identify the loaded index so results and gold sets can be tied to it."""
    row = conn.execute(
        "SELECT count(DISTINCT p.id), count(*), "
        "md5(string_agg(p.id || ':' || p.url || ':' || c.id || ':' || c.ord || ':' || md5(c.text), "
        "',' ORDER BY p.id, c.ord)) "
        "FROM chunks c JOIN postmortems p ON p.id = c.postmortem_id"
    ).fetchone()
    documents, chunks, digest = row
    if not chunks:
        raise RuntimeError("the index is empty; run `outage-matcher ingest` first")
    return IndexInfo(version=digest[:12], documents=documents, chunks=chunks)
