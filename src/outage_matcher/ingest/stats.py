"""Corpus statistics recorded to data/corpus_stats.json after an ingest."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from outage_matcher.ingest.collect import DATA_DIR
from outage_matcher.ingest.embed import MODELS
from outage_matcher.ingest.index import PreparedDoc

STATS_PATH = DATA_DIR / "corpus_stats.json"


def reason_bucket(reason: str) -> str:
    """Group failure reasons so counts are readable (drop per-page numbers and details)."""
    return reason.split(" (")[0].split(":")[0].strip()


def build_stats(
    docs: list[PreparedDoc],
    collect_failures: list[dict[str, str]],
    index_failures: list[dict[str, str]],
    *,
    today: date | None = None,
) -> dict:
    per_source: dict[str, dict[str, int]] = {}
    for doc in docs:
        bucket = per_source.setdefault(doc.entry.source, {"documents": 0, "chunks": 0})
        bucket["documents"] += 1
        bucket["chunks"] += len(doc.chunks)
    section_counts = Counter(c.section_type for doc in docs for c in doc.chunks)
    system_counts = Counter(doc.entry.system_type for doc in docs)
    failure_reasons = Counter(reason_bucket(f["reason"]) for f in collect_failures + index_failures)
    return {
        "generated": (today or date.today()).isoformat(),
        "embedding_models": MODELS,
        "document_count": len(docs),
        "chunk_count": sum(len(doc.chunks) for doc in docs),
        "per_source": dict(sorted(per_source.items())),
        "chunks_per_section_type": dict(sorted(section_counts.items())),
        "documents_per_system_type": dict(sorted(system_counts.items())),
        "failures": {
            "collect": len(collect_failures),
            "parse": len(index_failures),
            "by_reason": dict(sorted(failure_reasons.items())),
        },
    }


def write_stats(stats: dict, path: Path = STATS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
