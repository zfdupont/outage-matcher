"""Local embeddings via fastembed (no API cost)."""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from typing import Protocol

from outage_matcher.db import EMBEDDING_COLUMNS

MODELS: dict[str, str] = {
    "bge": "BAAI/bge-small-en-v1.5",
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
}
# BGE retrieval models expect this instruction on short queries (not on passages).
QUERY_PREFIX: dict[str, str] = {
    "bge": "Represent this sentence for searching relevant passages: ",
}
BATCH_SIZE = 64

assert set(MODELS) == set(EMBEDDING_COLUMNS)


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """Wraps a fastembed TextEmbedding model. The model loads on first use."""

    def __init__(self, key: str) -> None:
        if key not in MODELS:
            raise ValueError(f"unknown embedding model {key!r}; choose from {sorted(MODELS)}")
        self.key = key
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=MODELS[self.key])
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        return [vec.tolist() for vec in model.embed(list(texts), batch_size=BATCH_SIZE)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([QUERY_PREFIX.get(self.key, "") + text])[0]


@cache
def get_embedder(key: str) -> Embedder:
    return FastEmbedder(key)
