"""Run the M1 hand-written queries against both embedding models and print Markdown.

Usage: uv run python scripts/compare_embeddings_m1.py > docs/embedding-comparison-m1.md
Requires the index to be populated (`outage-matcher ingest`).
"""

import json
from datetime import date
from pathlib import Path

from outage_matcher import db
from outage_matcher.ingest.embed import MODELS
from outage_matcher.search import search

QUERIES = [
    "database failover caused split brain",
    "expired TLS certificate took down the API",
    "a bad configuration push to the load balancers caused a global outage",
    "disk filled up and the primary database stopped accepting writes",
    "BGP route leak made a CDN unreachable for customers",
]
K = 5


def main() -> None:
    stats = json.loads(Path("data/corpus_stats.json").read_text())
    print("# Embedding comparison, M1 (qualitative)\n")
    print(
        f"Generated {date.today().isoformat()} by `scripts/compare_embeddings_m1.py` over "
        f"{stats['document_count']} documents and {stats['chunk_count']} chunks "
        "(`data/corpus_stats.json`). Top 5 chunks per model, one row per chunk. "
        "Scores are cosine similarity and are only comparable within one model.\n"
    )
    with db.connect() as conn:
        for query in QUERIES:
            print(f"## Query: {query}\n")
            for key, name in MODELS.items():
                print(f"### {key} ({name})\n")
                print("| Rank | Title | Section | Score | URL |")
                print("| --- | --- | --- | --- | --- |")
                for rank, hit in enumerate(search(conn, query, key, K), start=1):
                    title = hit.title.replace("|", "/")
                    print(
                        f"| {rank} | {title} | {hit.section_type} | {hit.score:.3f} | {hit.url} |"
                    )
                print()


if __name__ == "__main__":
    main()
