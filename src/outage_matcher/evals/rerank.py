"""Local cross-encoder reranker (fastembed, no API cost)."""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"


class FastEmbedReranker:
    """Scores (query, chunk text) pairs with a cross-encoder. The model loads on first use."""

    def __init__(self, name: str = DEFAULT_RERANKER) -> None:
        self.name = name
        self._model = None

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name=self.name)
        return [float(s) for s in self._model.rerank(query, list(texts))]
