"""Run the agent on every gold query and judge the faithfulness of its answers.

    uv run python evals/run_faithfulness.py [--limit N] [--dry-run]

The agent (Anthropic) answers each gold query with that query's held-out root-cause chunks hidden
from its tools. A DeepSeek judge (a different model family than the agent, temperature 0) then
splits the answer into claims and marks each as supported or not by the cited chunks. Needs
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY` and the loaded index.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from outage_matcher import db
from outage_matcher.agent.models import AgentResult, RetrievalError
from outage_matcher.config import AgentConfig, load_config
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals import deepseek, faithfulness
from outage_matcher.evals.deepseek import DeepSeekClient, DeepSeekError
from outage_matcher.evals.gold import GOLD_PATH, GoldQuery, read_gold
from outage_matcher.evals.run_retrieval import (
    RESULTS_DIR,
    check_gold_matches_index,
    code_commit,
    sha256_file,
)

OUT_NAME = "faithfulness.json"
MAX_CONSECUTIVE_ERRORS = 3
# Rough per-query token budgets used only for the up-front estimate (agent: retrieve, grade,
# answer and the occasional rewrite; judge: cited excerpts plus the answer). Actuals are printed.
EST_AGENT_IN, EST_AGENT_OUT = 12000, 1500
EST_JUDGE_IN, EST_JUDGE_OUT = 4000, 600

AgentFactory = Callable[[GoldQuery], Any]  # returns an object with .ask(question) -> AgentResult


def estimate_tokens(queries: int) -> dict[str, int]:
    return {
        "agent_input": queries * EST_AGENT_IN,
        "agent_output": queries * EST_AGENT_OUT,
        "judge_input": queries * EST_JUDGE_IN,
        "judge_output": queries * EST_JUDGE_OUT,
    }


def evaluate_query(row: GoldQuery, agent: Any, judge: DeepSeekClient) -> dict[str, Any]:
    result: AgentResult = agent.ask(row.query)
    answer = result.answer
    record: dict[str, Any] = {
        "id": row.id,
        "query": row.query,
        "doc_id": row.doc_id,
        "no_match": answer.no_match,
        "likely_cause": answer.likely_cause,
        "suggested_fix": answer.suggested_fix,
        "cited_doc_ids": [c.doc_id for c in answer.citations],
        "cited_source_doc": row.doc_id in {c.doc_id for c in answer.citations},
        "retries": result.retries,
        "answer_notes": answer.notes,  # why a citation was dropped or the answer abstained
        "graded_relevant": sum(e["relevant"] for e in result.events if e["type"] == "grade"),
        "retrieved_doc_ids": sorted({c.doc_id for c in result.evidence}),
        "agent_usage": asdict(result.usage),
        "claims": [],
        "judge_usage": None,
        "error": None,
    }
    if answer.no_match:
        return record
    judgment = faithfulness.judge_answer(judge, result)
    record["judge_evidence_chars"] = sum(len(c.text) for c in faithfulness.cited_evidence(result))
    record["claims"] = [asdict(c) for c in judgment.claims]
    record["judge_usage"] = asdict(judgment.usage)
    return record


def run_all(
    gold: list[GoldQuery],
    make_agent: AgentFactory,
    judge: DeepSeekClient,
    log: Callable[[str], None] = lambda _msg: None,
) -> list[dict[str, Any]]:
    """One record per query. A failed query is recorded with its error and the run goes on,
    unless several fail in a row (a bad key or an outage), which raises."""
    records: list[dict[str, Any]] = []
    streak = 0
    for row in gold:
        try:
            record = evaluate_query(row, make_agent(row), judge)
            streak = 0
        except Exception as exc:  # API, retrieval and judge failures are per-query results
            if not _is_recoverable(exc):
                raise
            streak += 1
            record = {
                "id": row.id,
                "query": row.query,
                "doc_id": row.doc_id,
                "no_match": False,
                "claims": [],
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }
            if streak >= MAX_CONSECUTIVE_ERRORS:
                raise RuntimeError(
                    f"{streak} queries failed in a row; last error: {record['error']}"
                ) from exc
        records.append(record)
        log(f"{row.id}: " + _describe(record))
    return records


def _is_recoverable(exc: Exception) -> bool:
    import anthropic

    return isinstance(exc, (anthropic.APIError, RetrievalError, DeepSeekError))


def _describe(record: dict[str, Any]) -> str:
    if record.get("error"):
        return "error " + record["error"][:80]
    if record["no_match"]:
        return "no match"
    supported = sum(c["supported"] for c in record["claims"])
    return f"{supported}/{len(record['claims'])} claims supported"


def sum_usage(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    total = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for record in records:
        used = record.get(key)
        if used:
            total["input_tokens"] += used["input_tokens"]
            total["output_tokens"] += used["output_tokens"]
            total["calls"] += used.get("llm_calls", used.get("calls", 0))
    return total


def result_document(
    gold_path: Path,
    gold: list[GoldQuery],
    info: corpus_mod.IndexInfo,
    config: AgentConfig,
    judge_model: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run": "faithfulness",
        "date": date.today().isoformat(),
        "config": {
            "agent_model": config.model,
            "agent_max_retries": config.max_retries,
            "agent_retrieval": "pgvector search, bge embeddings, held-out chunks hidden per query",
            "judge_model": judge_model,
            "judge_temperature": faithfulness.JUDGE_TEMPERATURE,
            "judge_thinking": deepseek.THINKING["type"],
            "judge_prompt": {
                "system": faithfulness.JUDGE_SYSTEM,
                "user_template": faithfulness.JUDGE_USER_TEMPLATE,
                "evidence": "retrieved chunks of cited documents, "
                f"{faithfulness.EVIDENCE_CHARS} characters per chunk",
            },
            "note": "judge is a different model family from the agent",
        },
        "index": {"version": info.version, "documents": info.documents, "chunks": info.chunks},
        "gold": {
            "path": str(gold_path),
            "sha256": sha256_file(gold_path),
            "queries": len(gold),
            "generation": gold[0].generation if gold else None,
        },
        "code_commit": code_commit(),
        "metrics": faithfulness.summarize(records),
        "tokens": {
            "agent": sum_usage(records, "agent_usage"),
            "judge": sum_usage(records, "judge_usage"),
        },
        "per_query": records,
    }


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_faithfulness", description=__doc__.split("\n\n")[0])
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--limit", type=int, help="only the first N gold queries (cost control)")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR / OUT_NAME)
    parser.add_argument("--force", action="store_true", help="overwrite an existing result file")
    parser.add_argument("--allow-index-mismatch", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the token estimate and stop")
    return parser


def _print_estimate(queries: int) -> None:
    est = estimate_tokens(queries)
    print(
        f"estimated usage for {queries} queries (rough budgets, not measured): "
        f"agent {est['agent_input']} in / {est['agent_output']} out, "
        f"judge {est['judge_input']} in / {est['judge_output']} out"
    )


def main(argv: Sequence[str] | None = None) -> int:
    import anthropic

    from outage_matcher.agent.graph import OutageAgent
    from outage_matcher.agent.tools import ToolContext
    from outage_matcher.cli import _api_key, _make_client

    args = build_parser().parse_args(argv)
    if args.out.exists() and not args.force and not args.dry_run:
        _log(f"{args.out} exists; pass --force to replace it")
        return 1
    gold = read_gold(args.gold)[: args.limit]
    _print_estimate(len(gold))
    if args.dry_run:
        return 0
    anthropic_key, deepseek_key = _api_key(), deepseek.api_key()
    missing = [
        name
        for name, key in (("ANTHROPIC_API_KEY", anthropic_key), ("DEEPSEEK_API_KEY", deepseek_key))
        if key is None
    ]
    if missing:
        _log(f"{' and '.join(missing)} not set (or still the placeholder); set real keys to run")
        return 1
    config = load_config()
    judge = DeepSeekClient(deepseek_key, model=deepseek.model_id())
    client = _make_client(anthropic_key, config)
    try:
        with db.connect() as conn:
            info = corpus_mod.index_info(conn)
            if not args.allow_index_mismatch:
                check_gold_matches_index(gold, info)

            def make_agent(row: GoldQuery) -> Any:
                ctx = ToolContext(conn, exclude_chunk_ids=frozenset(row.held_out_chunk_ids))
                return OutageAgent(client, ctx, config)

            records = run_all(gold, make_agent, judge, _log)
    except (RuntimeError, anthropic.APIError) as exc:
        _log(f"error: {exc}")
        return 1
    document = result_document(args.gold, gold, info, config, judge.model, records)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    m, t = document["metrics"], document["tokens"]
    print(
        f"judged {m['answered_and_judged']} of {m['queries']} answers "
        f"({m['no_match']} no match, {m['errors']} errors): "
        f"claim support {m['claim_support_rate']}, faithful answers {m['faithful_answer_rate']}"
    )
    print(f"actual usage: agent {t['agent']}, judge {t['judge']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
