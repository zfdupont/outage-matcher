"""Score retrieval on the gold set: recall@k and MRR for one configuration.

    uv run python -m outage_matcher.evals.run_retrieval --model bge --chunking section

Each query's held-out root-cause chunks are excluded, and the source document (plus confirmed
near-duplicates) counts as relevant. The run is written to evals/results/<run-name>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from outage_matcher import db
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals import metrics
from outage_matcher.evals.chunking import CACHE_DIR, CHUNKINGS, make_chunking
from outage_matcher.evals.gold import GOLD_PATH, GoldQuery, read_gold
from outage_matcher.evals.rerank import DEFAULT_RERANKER, FastEmbedReranker
from outage_matcher.evals.retrieval import RERANK_DEPTH, Retriever, load_corpus
from outage_matcher.ingest.embed import MODELS, get_embedder

RESULTS_DIR = Path("evals/results")
TOP_DOCS_RECORDED = 10
SEARCH_DESCRIPTION = (
    "exact cosine similarity over all chunks, held-out chunks excluded per query, "
    "documents ranked by best chunk"
)


@dataclass(frozen=True)
class QueryResult:
    id: str
    doc_id: int
    relevant_doc_ids: list[int]
    rank: int | None
    top_doc_ids: list[int]


def evaluate(gold: list[GoldQuery], retriever: Retriever) -> list[QueryResult]:
    results = []
    for row in gold:
        excluded = retriever.corpus.excluded_indices(row.doc_id, row.held_out_ords)
        ranked = retriever.rank_documents(row.query, excluded)
        relevant = row.relevant_doc_ids
        results.append(
            QueryResult(
                row.id,
                row.doc_id,
                relevant,
                metrics.first_relevant_rank(ranked, relevant),
                ranked[:TOP_DOCS_RECORDED],
            )
        )
    return results


def run_name(model: str, chunking: str, reranker: str | None) -> str:
    parts = [model, chunking]
    if reranker:
        parts.append("rerank-" + reranker.rsplit("/", 1)[-1].lower())
    return "-".join(parts)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def result_document(
    name: str,
    config: dict[str, Any],
    info: corpus_mod.IndexInfo,
    gold_path: Path,
    gold: list[GoldQuery],
    results: list[QueryResult],
    today: date | None = None,
) -> dict[str, Any]:
    ranks = [r.rank for r in results]
    return {
        "run": name,
        "date": (today or date.today()).isoformat(),
        "config": config,
        "index": {"version": info.version, "documents": info.documents, "chunks": info.chunks},
        "gold": {
            "path": str(gold_path),
            "sha256": sha256_file(gold_path),
            "queries": len(gold),
            "generation": gold[0].generation if gold else None,
        },
        "code_commit": code_commit(),
        "metrics": metrics.compute_metrics(ranks),
        "per_query": [
            {
                "id": r.id,
                "doc_id": r.doc_id,
                "relevant_doc_ids": r.relevant_doc_ids,
                "rank": r.rank,
                "top_doc_ids": r.top_doc_ids,
            }
            for r in results
        ],
    }


def check_gold_matches_index(gold: list[GoldQuery], info: corpus_mod.IndexInfo) -> None:
    stale = sorted({g.index_version for g in gold if g.index_version != info.version})
    if stale:
        raise ValueError(
            f"gold set was built on index {stale} but the loaded index is {info.version}; "
            "rebuild the gold set or pass --allow-index-mismatch"
        )


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def format_metrics(values: dict[str, float]) -> str:
    return "  ".join(f"{k} {v:.3f}" for k, v in values.items())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_retrieval", description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", choices=sorted(MODELS), required=True, help="embedding model")
    parser.add_argument(
        "--chunking",
        choices=CHUNKINGS,
        default="section",
        help="section: the indexed chunks; neighbor: each chunk embedded with adjacent context",
    )
    parser.add_argument(
        "--reranker",
        nargs="?",
        const=DEFAULT_RERANKER,
        metavar="MODEL",
        help=f"rerank the top chunks with a fastembed cross-encoder (default {DEFAULT_RERANKER})",
    )
    parser.add_argument("--rerank-depth", type=int, default=RERANK_DEPTH, help="chunks reranked")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR, help="embedding cache")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--name", help="run name (default: derived from the configuration)")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--force", action="store_true", help="overwrite an existing result file")
    parser.add_argument(
        "--allow-index-mismatch",
        action="store_true",
        help="run even if the gold set was built on a different index version",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    name = args.name or run_name(args.model, args.chunking, args.reranker)
    out = args.results_dir / f"{name}.json"
    if out.exists() and not args.force:
        _log(f"{out} exists; pass --force to replace it")
        return 1
    gold = read_gold(args.gold)
    with db.connect() as conn:
        info = corpus_mod.index_info(conn)
        if not args.allow_index_mismatch:
            check_gold_matches_index(gold, info)
        corpus = load_corpus(conn, args.model)
    chunking = make_chunking(args.chunking, args.cache_dir)
    reranker = FastEmbedReranker(args.reranker) if args.reranker else None
    retriever = Retriever(
        corpus, get_embedder(args.model), chunking, reranker, rerank_depth=args.rerank_depth
    )
    config = {
        "embedding_model": args.model,
        "embedding_model_name": MODELS[args.model],
        "chunking": chunking.name,
        "chunking_params": chunking.params,
        "reranker": args.reranker,
        "rerank_depth": args.rerank_depth if args.reranker else None,
        "search": SEARCH_DESCRIPTION,
    }
    results = evaluate(gold, retriever)
    document = result_document(name, config, info, args.gold, gold, results)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"{name}: {len(gold)} queries  {format_metrics(document['metrics'])}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
