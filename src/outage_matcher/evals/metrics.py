"""Retrieval metrics over document ranks.

A query's rank is the 1-based position of its first relevant document in the ranked list of
distinct documents (a document sits where its best chunk does), or None when no relevant document
is ranked.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

KS: tuple[int, ...] = (1, 3, 5, 10)


def first_relevant_rank(ranked_doc_ids: Sequence[int], relevant: Collection[int]) -> int | None:
    for position, doc_id in enumerate(ranked_doc_ids, start=1):
        if doc_id in relevant:
            return position
    return None


def _check(ranks: Sequence[int | None]) -> None:
    if not ranks:
        raise ValueError("no queries to score")
    if any(r is not None and r < 1 for r in ranks):
        raise ValueError("ranks are 1-based")


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Fraction of queries whose first relevant document is within the top k."""
    if k < 1:
        raise ValueError("k must be at least 1")
    _check(ranks)
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    """Mean of 1/rank, counting an unranked query as 0."""
    _check(ranks)
    return sum(1 / r for r in ranks if r is not None) / len(ranks)


def compute_metrics(ranks: Sequence[int | None], ks: Sequence[int] = KS) -> dict[str, float]:
    metrics = {f"recall@{k}": recall_at_k(ranks, k) for k in ks}
    metrics["mrr"] = mean_reciprocal_rank(ranks)
    return metrics
