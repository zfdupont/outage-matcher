"""Alternative chunking strategies for the retrieval evals."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from outage_matcher.evals.retrieval import ChunkingStrategy, Corpus, SectionChunking, unit
from outage_matcher.ingest.embed import Embedder
from outage_matcher.ingest.index import embed_all

NEIGHBOR_CHARS = 200
CACHE_DIR = Path("evals/cache")


def context_text(corpus: Corpus, index: int, skip: frozenset[int], chars: int) -> str:
    """A chunk followed by the tail of the chunk before it and the head of the chunk after it,
    when those sit in the same document and are not in `skip` (held-out chunks)."""
    parts = [corpus.texts[index]]
    for other in (index - 1, index + 1):
        if not 0 <= other < len(corpus.texts) or other in skip:
            continue
        if corpus.doc_ids[other] != corpus.doc_ids[index]:
            continue
        text = corpus.texts[other]
        parts.append(text[-chars:] if other < index else text[:chars])
    return "\n".join(parts)


class NeighborChunking:
    """Section chunks embedded together with a little context from the adjacent chunks.

    The chunk text that is returned and reranked stays the plain chunk. When a query holds a
    chunk out, its neighbors are re-embedded without that chunk's text so it cannot leak back in
    through their context.
    """

    name = "neighbor"

    def __init__(self, chars: int = NEIGHBOR_CHARS, cache_dir: Path | None = CACHE_DIR) -> None:
        self.chars = chars
        self.cache_dir = cache_dir
        self.params = {"neighbor_chars": chars}

    def _cache_path(self, corpus: Corpus) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256("\x00".join(corpus.texts).encode()).hexdigest()[:12]
        return self.cache_dir / f"neighbor-{corpus.model}-{self.chars}-{digest}.npy"

    def matrix(self, corpus: Corpus, embedder: Embedder) -> np.ndarray:
        path = self._cache_path(corpus)
        if path is not None and path.exists():
            return np.load(path)
        texts = [context_text(corpus, i, frozenset(), self.chars) for i in range(len(corpus.texts))]
        vectors = unit(np.asarray(embed_all(texts, embedder), dtype=np.float32))
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, vectors)
        return vectors

    def patched_rows(
        self, corpus: Corpus, embedder: Embedder, excluded: np.ndarray
    ) -> dict[int, np.ndarray]:
        skip = frozenset(int(i) for i in excluded)
        affected = sorted(
            {j for i in skip for j in (i - 1, i + 1) if 0 <= j < len(corpus.texts)} - skip
        )
        affected = [
            j for j in affected if any(corpus.doc_ids[j] == corpus.doc_ids[i] for i in skip)
        ]
        if not affected:
            return {}
        texts = [context_text(corpus, j, skip, self.chars) for j in affected]
        vectors = embedder.embed_documents(texts)
        return {j: np.asarray(v, dtype=np.float32) for j, v in zip(affected, vectors, strict=True)}


CHUNKINGS: tuple[str, ...] = ("section", "neighbor")


def make_chunking(name: str, cache_dir: Path | None = CACHE_DIR) -> ChunkingStrategy:
    if name == "section":
        return SectionChunking()
    if name == "neighbor":
        return NeighborChunking(cache_dir=cache_dir)
    raise ValueError(f"unknown chunking {name!r}; choose from {list(CHUNKINGS)}")
