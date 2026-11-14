"""Command line entry point: `outage-matcher ingest`, `search`, `ask` and `serve`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from outage_matcher import db, observability
from outage_matcher.config import load_config
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


def _api_key() -> str | None:
    """ANTHROPIC_API_KEY from the environment or .env; the .env.example placeholder is unset."""
    load_dotenv()
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return None if not key or key.startswith("your-") else key


def _make_client(api_key: str, config):
    """Anthropic client with an explicit timeout and retry count (the SDK default is 10 minutes)."""
    import anthropic

    return anthropic.Anthropic(
        api_key=api_key, timeout=config.request_timeout, max_retries=config.api_max_retries
    )


def _build_agent(conn, client, config):
    # Imported here so `ingest` and `search` do not pay for loading langgraph.
    from outage_matcher.agent.graph import OutageAgent
    from outage_matcher.agent.tools import ToolContext

    return OutageAgent(client, ToolContext(conn), config)


def cmd_ask(args: argparse.Namespace) -> int:
    import anthropic

    from outage_matcher.agent import transcript

    api_key = _api_key()
    if api_key is None:
        _log(
            "ANTHROPIC_API_KEY is not set (or is still the .env.example placeholder); "
            "set a real key in the environment or .env to run `ask`."
        )
        return 1
    config = load_config()
    try:
        with db.connect() as conn:
            result = _build_agent(conn, _make_client(api_key, config), config).ask(args.question)
    except anthropic.APIError as exc:  # network, auth, rate limit or bad model name
        _log(f"error: Anthropic API call failed: {exc}")
        return 1
    finally:
        observability.flush()
    print(transcript.render_answer(result))
    print(transcript.render_usage(result))
    if args.transcript:
        path = Path(args.transcript)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(transcript.render_markdown(result, config.model), encoding="utf-8")
        _log(f"transcript written to {path}")
    return 0


def serve_agent_factory():
    """Agent for the API, or None (so `/ask` answers 503) when there is no real API key."""
    from outage_matcher.api.agent import ApiAgent

    api_key = _api_key()
    if api_key is None:
        _log(
            "ANTHROPIC_API_KEY is not set (or is still the .env.example placeholder); "
            "POST /ask will answer 503 until a real key is configured."
        )
        return None
    config = load_config()
    client = _make_client(api_key, config)
    return ApiAgent(lambda conn: _build_agent(conn, client, config))


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from outage_matcher.api.app import create_app

    load_dotenv()  # Langfuse keys come from .env in local runs
    uvicorn.run(create_app(serve_agent_factory), host=args.host, port=args.port)
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

    ask = sub.add_parser(
        "ask", help="describe an incident, get a likely cause and fix with citations"
    )
    ask.add_argument("question", help="incident description")
    ask.add_argument("--transcript", metavar="PATH", help="also save a Markdown transcript here")
    ask.set_defaults(func=cmd_ask)
    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=positive_int, default=8000)
    serve.set_defaults(func=cmd_serve)
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
