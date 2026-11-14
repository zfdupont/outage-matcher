"""Exact dense retrieval over the whole index for the evals.

The eval loads every chunk vector into memory and ranks by exact cosine similarity, so a query's
held-out chunks can be excluded without touching the database index. Documents are ranked by their
best chunk. This is the same similarity the agent's pgvector search uses, minus the approximate
HNSW scan.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import psycopg

from outage_matcher.db import EMBEDDING_COLUMNS
from outage_matcher.evals.corpus import DocRow, load_docs
from outage_matcher.ingest.embed import Embedder

RERANK_DEPTH = 50


def unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


@dataclass
class Corpus:
    """All chunks of the index in one flat order (by document id, then position)."""

    model: str
    docs: list[DocRow]
    doc_ids: np.ndarray  # document id of every chunk
    ords: np.ndarray  # position of every chunk within its document
    texts: list[str]
    embeddings: np.ndarray  # stored vectors for `model`, unit length

    def excluded_indices(self, doc_id: int, ords: Sequence[int]) -> np.ndarray:
        """Flat indices of the held-out chunks. A stale gold set fails loudly here."""
        indices = np.flatnonzero((self.doc_ids == doc_id) & np.isin(self.ords, list(ords)))
        if len(indices) != len(set(ords)):
            raise ValueError(f"document {doc_id} has no chunks at positions {sorted(ords)}")
        return indices


def build_corpus(docs: list[DocRow], vectors: dict[int, np.ndarray], model: str) -> Corpus:
    """Assemble a corpus from documents and a chunk id to vector map."""
    flat = [(doc.id, chunk) for doc in docs for chunk in doc.chunks]
    return Corpus(
        model=model,
        docs=docs,
        doc_ids=np.array([doc_id for doc_id, _ in flat]),
        ords=np.array([chunk.ord for _, chunk in flat]),
        texts=[chunk.text for _, chunk in flat],
        embeddings=unit(np.stack([vectors[chunk.id] for _, chunk in flat]).astype(np.float32)),
    )


def _as_array(vector: object) -> np.ndarray:
    """pgvector returns its own Vector type unless the numpy adapter is active."""
    to_numpy = getattr(vector, "to_numpy", None)
    return to_numpy() if to_numpy else np.asarray(vector)


def load_corpus(conn: psycopg.Connection, model: str) -> Corpus:
    if model not in EMBEDDING_COLUMNS:
        raise ValueError(f"unknown model {model!r}; choose from {sorted(EMBEDDING_COLUMNS)}")
    docs = load_docs(conn)
    rows = conn.execute(f"SELECT id, {EMBEDDING_COLUMNS[model]} FROM chunks").fetchall()
    return build_corpus(docs, {chunk_id: _as_array(vec) for chunk_id, vec in rows}, model)


class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


class ChunkingStrategy(Protocol):
    """How chunks are embedded for retrieval. The text shown to readers is always the chunk."""

    name: str
    params: dict[str, object]  # settings recorded in result files

    def matrix(self, corpus: Corpus, embedder: Embedder) -> np.ndarray: ...

    def patched_rows(
        self, corpus: Corpus, embedder: Embedder, excluded: np.ndarray
    ) -> dict[int, np.ndarray]:
        """Vectors that change when `excluded` chunks are held out (flat index to vector)."""
        ...


class SectionChunking:
    """The indexed chunks as stored: one embedding per section-typed chunk."""

    name = "section"
    params: dict[str, object] = {}

    def matrix(self, corpus: Corpus, embedder: Embedder) -> np.ndarray:
        return corpus.embeddings

    def patched_rows(
        self, corpus: Corpus, embedder: Embedder, excluded: np.ndarray
    ) -> dict[int, np.ndarray]:
        return {}


class Retriever:
    def __init__(
        self,
        corpus: Corpus,
        embedder: Embedder,
        chunking: ChunkingStrategy | None = None,
        reranker: Reranker | None = None,
        rerank_depth: int = RERANK_DEPTH,
    ) -> None:
        self.corpus = corpus
        self.embedder = embedder
        self.chunking = chunking or SectionChunking()
        self.reranker = reranker
        self.rerank_depth = rerank_depth
        self.matrix = self.chunking.matrix(corpus, embedder)

    def chunk_order(self, query: str, excluded: np.ndarray) -> np.ndarray:
        """Flat chunk indices, best first, without the excluded chunks."""
        q = unit(np.asarray(self.embedder.embed_query(query), dtype=np.float32))
        sims = self.matrix @ q
        for index, vector in self.chunking.patched_rows(
            self.corpus, self.embedder, excluded
        ).items():
            sims[index] = unit(vector) @ q
        sims[excluded] = -np.inf
        order = np.argsort(-sims, kind="stable")[: len(sims) - len(excluded)]
        if self.reranker is None:
            return order
        head, tail = order[: self.rerank_depth], order[self.rerank_depth :]
        scores = self.reranker.score(query, [self.corpus.texts[i] for i in head])
        reordered = head[np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")]
        return np.concatenate([reordered, tail])

    def rank_documents(self, query: str, excluded: np.ndarray) -> list[int]:
        """Distinct document ids, each placed where its best chunk is."""
        seen: dict[int, None] = {}
        for index in self.chunk_order(query, excluded):
            seen.setdefault(int(self.corpus.doc_ids[index]), None)
        return list(seen)
