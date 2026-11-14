"""Shared offline test helpers (a fake embedder and a small postmortem page)."""

import hashlib

import numpy as np

from outage_matcher import db
from outage_matcher.ingest.collect import ManifestEntry

PAGE = (
    "<html><body><article><h1>DB outage</h1><p>"
    + "The primary lost its leader and writes stopped for a while. " * 6
    + "</p><h2>Root cause</h2><p>"
    + "A partition caused split brain between two nodes. " * 6
    + "</p></article></body></html>"
)


class FakeEmbedder:
    """Deterministic 384-dim unit vectors derived from the text hash."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.calls: list[int] = []

    def _vec(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
        v = np.random.default_rng(seed).normal(size=db.EMBEDDING_DIM)
        return (v / np.linalg.norm(v)).tolist()

    def embed_documents(self, texts):
        self.calls.append(len(texts))
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(self.prefix + text)


def entry(doc_id: str, url: str, source: str = "community") -> ManifestEntry:
    return ManifestEntry(doc_id, url, f"Title {doc_id}", source, "2026-11-13", "database")
