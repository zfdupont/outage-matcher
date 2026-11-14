"""Command line entry point: `outage-matcher ingest` and `outage-matcher search`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from outage_matcher import db
from outage_matcher.ingest import collect as collect_mod
from outage_matcher.ingest import index as index_mod
from outage_matcher.ingest import stats as stats_mod
from outage_matcher.ingest.embed import MODELS
from outage_matcher.search import search


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def cmd_ingest(args: argparse.Namespace) -> int:
    failures: list[dict[str, str]] = []
    if args.skip_collect:
        entries = collect_mod.read_manifest()
        if not entries:
            _log("no manifest found; run without --skip-collect first")
            return 1
    else:
        entries, failures = collect_mod.collect(max_docs=args.max_docs, log=_log)
    docs, parse_failures = index_mod.prepare_documents(entries)
    with db.connect() as conn:
        result = index_mod.write_index(conn, docs, log=_log)
    stats = stats_mod.build_stats(docs, failures, parse_failures)
    stats_mod.write_stats(stats)
    print(f"indexed {result.documents} documents, {result.chunks} chunks")
    print(f"failures: collect {len(failures)}, parse {len(parse_failures)}")
    print(json.dumps({"per_source": stats["per_source"]}))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    models = [args.model] if args.model else list(MODELS)
    with db.connect() as conn:
        for model in models:
            hits = search(conn, args.query, model, args.k, system_type=args.system_type)
            print(f"== {model} ({MODELS[model]})")
            if not hits:
                print("  no results (is the index empty? run `outage-matcher ingest`)")
            for rank, hit in enumerate(hits, start=1):
                print(f"{rank}. {hit.title} [{hit.section_type}] score={hit.score:.3f}")
                print(f"   {hit.url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outage-matcher", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="collect, chunk, embed and index postmortems")
    ingest.add_argument("--max-docs", type=int, default=collect_mod.DEFAULT_MAX_DOCS)
    ingest.add_argument(
        "--skip-collect", action="store_true", help="reuse data/manifest.jsonl and data/raw"
    )
    ingest.set_defaults(func=cmd_ingest)

    find = sub.add_parser("search", help="search indexed postmortems")
    find.add_argument("query")
    find.add_argument("--model", choices=sorted(MODELS), help="default: both models")
    find.add_argument("--k", type=int, default=5)
    find.add_argument("--system-type", help="restrict to a system type label")
    find.set_defaults(func=cmd_search)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
