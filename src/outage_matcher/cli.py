"""Command line entry point: `outage-matcher ingest` and `outage-matcher search`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import psycopg

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
        failures = collect_mod.read_failures()
        if not entries:
            _log("no manifest found; run without --skip-collect first")
            return 1
    else:
        entries, failures = collect_mod.collect(max_docs=args.max_docs, log=_log)
    docs, parse_failures = index_mod.prepare_documents(entries)
    if not docs:
        _log(
            f"error: none of the {len(entries)} manifest entries could be chunked "
            f"({len(parse_failures)} failures, for example missing data/raw files); "
            "index and stats left unchanged. Run `outage-matcher ingest` without --skip-collect."
        )
        return 1
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


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outage-matcher", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="collect, chunk, embed and index postmortems")
    ingest.add_argument("--max-docs", type=positive_int, default=collect_mod.DEFAULT_MAX_DOCS)
    ingest.add_argument(
        "--skip-collect", action="store_true", help="reuse data/manifest.jsonl and data/raw"
    )
    ingest.set_defaults(func=cmd_ingest)

    find = sub.add_parser("search", help="search indexed postmortems")
    find.add_argument("query")
    find.add_argument("--model", choices=sorted(MODELS), help="default: both models")
    find.add_argument("--k", type=positive_int, default=5)
    find.add_argument("--system-type", help="restrict to a system type label")
    find.set_defaults(func=cmd_search)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (psycopg.OperationalError, RuntimeError, ValueError) as exc:
        # Unreachable database, missing DATABASE_URL, bad search arguments: one line, exit 1.
        _log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
