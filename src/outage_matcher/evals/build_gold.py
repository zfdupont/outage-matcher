"""Build the gold set: symptoms-only queries for postmortems whose root cause is held out.

    uv run python evals/build_gold.py [--count 40] [--dry-run]

For each chosen postmortem the root-cause chunks are the held-out section: retrieval evals
exclude them, and the query is written (by DeepSeek) from the remaining sections without the
root-cause wording. Needs a loaded index and `DEEPSEEK_API_KEY` (unless `--dry-run`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from outage_matcher import db
from outage_matcher.evals import corpus, deepseek, gold
from outage_matcher.evals.deepseek import DeepSeekError, TokenUsage
from outage_matcher.search import search

DEFAULT_COUNT = 40
DEFAULT_TEMPERATURE = 0.2
DEFAULT_ATTEMPTS = 3
NEAR_DUP_CANDIDATES = 6
NEAR_DUP_SEARCH_K = 40

CandidateFinder = Callable[[str, corpus.DocRow], list[gold.NearDupCandidate]]


@dataclass
class BuildStats:
    attempted: int = 0
    unusable: int = 0
    leaky: int = 0
    errors: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    skipped: list[str] = field(default_factory=list)  # one line per skipped document


def draft_query(
    client: deepseek.DeepSeekClient,
    doc: corpus.DocRow,
    stats: BuildStats,
    *,
    temperature: float,
    max_attempts: int,
) -> tuple[str, str] | None:
    """A leak-free query and the generation notes, or None when the document is skipped."""
    messages = [
        {"role": "system", "content": gold.QUERY_SYSTEM},
        {"role": "user", "content": gold.query_prompt(doc)},
    ]
    problems: list[str] = []
    for attempt in range(1, max_attempts + 1):
        reply = client.chat_json(messages, temperature=temperature, max_tokens=400)
        stats.usage = stats.usage.plus(reply.usage)
        if reply.data.get("usable") is not True:
            stats.unusable += 1
            stats.skipped.append(f"{doc.id} {doc.title[:50]}: model marked it unusable")
            return None
        query = reply.data.get("query")
        query = query.strip() if isinstance(query, str) else ""
        problems = gold.leak_problems(query, doc) if query else ["the query is empty"]
        if not problems:
            note = reply.data.get("notes")
            note = note.strip() if isinstance(note, str) else ""
            return query, f"{note} (accepted on attempt {attempt} of {max_attempts})".strip()
        messages += [
            {"role": "assistant", "content": reply.content},
            {"role": "user", "content": gold.retry_prompt(problems)},
        ]
    stats.leaky += 1
    stats.skipped.append(f"{doc.id} {doc.title[:50]}: rejected {max_attempts} times ({problems})")
    return None


def suggest_near_duplicates(
    client: deepseek.DeepSeekClient,
    doc: corpus.DocRow,
    candidates: list[gold.NearDupCandidate],
    stats: BuildStats,
) -> list[gold.NearDuplicate]:
    if not candidates:
        return []
    messages = [
        {"role": "system", "content": gold.NEAR_DUP_SYSTEM},
        {"role": "user", "content": gold.near_duplicate_prompt(doc, candidates)},
    ]
    reply = client.chat_json(messages, temperature=0.0, max_tokens=400)
    stats.usage = stats.usage.plus(reply.usage)
    return gold.parse_near_duplicates(reply.data, candidates)


def build_gold(
    docs: list[corpus.DocRow],
    client: deepseek.DeepSeekClient,
    find_candidates: CandidateFinder,
    *,
    index_version: str,
    count: int = DEFAULT_COUNT,
    seed: int = 0,
    temperature: float = DEFAULT_TEMPERATURE,
    max_attempts: int = DEFAULT_ATTEMPTS,
    today: date | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> tuple[list[gold.GoldQuery], BuildStats]:
    stats = BuildStats()
    rows: list[gold.GoldQuery] = []
    generation = {
        "model": client.model,
        "temperature": temperature,
        "date": (today or date.today()).isoformat(),
        "seed": seed,
    }
    for doc in gold.select_candidates(docs, seed):
        if len(rows) >= count:
            break
        stats.attempted += 1
        try:
            drafted = draft_query(
                client, doc, stats, temperature=temperature, max_attempts=max_attempts
            )
            if drafted is None:
                continue
            query, notes = drafted
            near = suggest_near_duplicates(client, doc, find_candidates(query, doc), stats)
        except DeepSeekError as exc:
            stats.errors += 1
            stats.skipped.append(f"{doc.id} {doc.title[:50]}: {exc}")
            continue
        held_out = doc.root_cause_chunks
        rows.append(
            gold.GoldQuery(
                id=f"q{len(rows) + 1:03d}",
                query=query,
                doc_id=doc.id,
                doc_url=doc.url,
                doc_title=doc.title,
                source=doc.source,
                held_out_chunk_id=held_out[0].id,
                held_out_chunk_ids=[c.id for c in held_out],
                held_out_ords=[c.ord for c in held_out],
                held_out_heading=held_out[0].text.split("\n", 1)[0][:200],
                index_version=index_version,
                generation=generation,
                notes=notes,
                near_duplicates=near,
            )
        )
        log(f"{rows[-1].id}: {doc.title[:60]} ({len(near)} suggested near-duplicates)")
    return rows, stats


def db_candidate_finder(conn, docs: list[corpus.DocRow]) -> CandidateFinder:
    """Near-duplicate candidates: the best other documents for the query under the bge model."""
    by_id = {d.id: d for d in docs}

    def find(query: str, doc: corpus.DocRow) -> list[gold.NearDupCandidate]:
        found: dict[int, gold.NearDupCandidate] = {}
        for hit in search(conn, query, "bge", NEAR_DUP_SEARCH_K):
            if hit.postmortem_id != doc.id and hit.postmortem_id not in found:
                title = by_id[hit.postmortem_id].title
                found[hit.postmortem_id] = gold.NearDupCandidate(
                    hit.postmortem_id, title, hit.url, hit.text
                )
        return list(found.values())[:NEAR_DUP_CANDIDATES]

    return find


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_gold", description=__doc__.split("\n\n")[0])
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="target number of queries")
    parser.add_argument("--seed", type=int, default=0, help="seed for the candidate order")
    parser.add_argument("--out", type=Path, default=gold.GOLD_PATH)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--force", action="store_true", help="overwrite an existing gold file")
    parser.add_argument(
        "--dry-run", action="store_true", help="list the chosen documents; call no API"
    )
    args = parser.parse_args(argv)

    if args.out.exists() and not args.force and not args.dry_run:
        _log(f"{args.out} exists; pass --force to replace it")
        return 1
    key = None if args.dry_run else deepseek.api_key()
    if not args.dry_run and key is None:
        _log(
            "DEEPSEEK_API_KEY is not set (or is still the .env.example placeholder); "
            "set a real key in the environment or .env, or use --dry-run."
        )
        return 1
    with db.connect() as conn:
        info = corpus.index_info(conn)
        docs = corpus.load_docs(conn)
        candidates = gold.select_candidates(docs, args.seed)
        _log(f"index {info.version}: {info.documents} documents, {info.chunks} chunks")
        _log(f"{len(candidates)} documents have a clear root-cause section")
        if args.dry_run:
            for doc in candidates[: args.count]:
                held = sum(len(c.text) for c in doc.root_cause_chunks)
                print(f"{doc.id}\t{doc.source}\t{held} root-cause chars\t{doc.title}")
            return 0
        client = deepseek.DeepSeekClient(key, model=deepseek.model_id())
        rows, stats = build_gold(
            docs,
            client,
            db_candidate_finder(conn, docs),
            index_version=info.version,
            count=args.count,
            seed=args.seed,
            temperature=args.temperature,
            max_attempts=args.max_attempts,
            log=_log,
        )
    for line in stats.skipped:
        _log(f"skipped {line}")
    if not rows:
        _log("no queries were generated; nothing written")
        return 1
    gold.write_gold(rows, args.out)
    print(f"wrote {len(rows)} queries to {args.out} (target {args.count})")
    print(
        f"documents tried {stats.attempted}: unusable {stats.unusable}, leaky {stats.leaky}, "
        f"api errors {stats.errors}"
    )
    print(f"DeepSeek usage ({client.model}): {stats.usage.describe()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
