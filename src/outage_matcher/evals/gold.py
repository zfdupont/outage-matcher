"""Gold-set records, candidate selection, query generation checks and prompts."""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from outage_matcher.evals.corpus import DocRow

GOLD_PATH = Path("evals/gold.jsonl")

MIN_ROOT_CAUSE_CHARS = 200  # a root-cause section has to say something
MIN_SYMPTOM_CHUNKS = 2  # chunks left in the index once the root cause is held out
MIN_SYMPTOM_CHARS = 800
# Monthly availability digests cover several unrelated incidents, so one symptom query does not
# identify one document in them.
DIGEST_TITLE = re.compile(r"availability (report|this week)", re.I)

SYMPTOM_PROMPT_CHARS = 5000
ROOT_PROMPT_CHARS = 1500
MIN_QUERY_WORDS = 8
MAX_QUERY_WORDS = 90
ROOT_RUN = 5  # a query may not share this many consecutive words with the root-cause text
DOC_RUN = 8  # ... or this many with any text of the source document
GENERIC_HOST_WORDS = frozenset(
    "www com org net io co dev app blog status cloud engineering news research".split()
)


@dataclass
class NearDuplicate:
    doc_id: int
    title: str
    url: str
    reason: str  # what the LLM said makes it the same incident
    confirmed: bool = False  # set to true by hand after checking; only then does it count


@dataclass
class GoldQuery:
    id: str
    query: str
    doc_id: int  # postmortems.id of the source document
    doc_url: str
    doc_title: str
    source: str
    held_out_chunk_id: int  # the first held-out root-cause chunk (chunks.id)
    held_out_chunk_ids: list[int]  # every root-cause chunk of the document, all excluded
    held_out_ords: list[int]  # their positions in the document (stable across re-indexing)
    held_out_heading: str
    index_version: str  # `corpus.index_info` of the index the ids refer to
    generation: dict[str, Any]  # model, temperature, date
    notes: str
    near_duplicates: list[NearDuplicate] = field(default_factory=list)

    @property
    def relevant_doc_ids(self) -> list[int]:
        """The source document plus near-duplicates a person has confirmed."""
        return [self.doc_id, *[n.doc_id for n in self.near_duplicates if n.confirmed]]


def gold_from_json(row: dict[str, Any]) -> GoldQuery:
    near = [NearDuplicate(**n) for n in row.get("near_duplicates", [])]
    return GoldQuery(**{**row, "near_duplicates": near})


def read_gold(path: Path = GOLD_PATH) -> list[GoldQuery]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; build it with `evals/build_gold.py`")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [gold_from_json(row) for row in rows]


def write_gold(rows: list[GoldQuery], path: Path = GOLD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(asdict(row), ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


# ----- candidate selection ----------------------------------------------------------------------


def is_eligible(doc: DocRow) -> bool:
    root = doc.root_cause_chunks
    other = doc.other_chunks
    return (
        not DIGEST_TITLE.search(doc.title)
        and sum(len(c.text) for c in root) >= MIN_ROOT_CAUSE_CHARS
        and len(other) >= MIN_SYMPTOM_CHUNKS
        and sum(len(c.text) for c in other) >= MIN_SYMPTOM_CHARS
    )


def select_candidates(docs: list[DocRow], seed: int = 0) -> list[DocRow]:
    """Documents with a clear root-cause section, in a seeded random order."""
    eligible = sorted((d for d in docs if is_eligible(d)), key=lambda d: d.id)
    random.Random(seed).shuffle(eligible)
    return eligible


# ----- leakage checks ---------------------------------------------------------------------------


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def shares_run(query_words: list[str], text_words: list[str], n: int) -> bool:
    """True when `n` consecutive words of the query also appear consecutively in the text."""
    if len(query_words) < n:
        return False
    grams = {tuple(text_words[i : i + n]) for i in range(len(text_words) - n + 1)}
    return any(tuple(query_words[i : i + n]) in grams for i in range(len(query_words) - n + 1))


def host_words(url: str) -> set[str]:
    """Distinctive parts of the host name, for example cloudflare or mozilla."""
    host = urlparse(url).hostname or ""
    parts = re.split(r"[.\-]", host.lower())
    return {p for p in parts if len(p) >= 4 and p not in GENERIC_HOST_WORDS}


def leak_problems(query: str, doc: DocRow) -> list[str]:
    """Reasons the query would make retrieval trivial or reveal the held-out cause."""
    q = words(query)
    problems: list[str] = []
    if not MIN_QUERY_WORDS <= len(q) <= MAX_QUERY_WORDS:
        problems.append(f"length must be {MIN_QUERY_WORDS} to {MAX_QUERY_WORDS} words")
    root_words = words(" ".join(c.text for c in doc.root_cause_chunks))
    if shares_run(q, root_words, ROOT_RUN):
        problems.append(f"copies {ROOT_RUN} or more consecutive words of the root-cause section")
    doc_words = words(" ".join(c.text for c in doc.chunks))
    if shares_run(q, doc_words, DOC_RUN):
        problems.append(f"copies {DOC_RUN} or more consecutive words of the postmortem")
    named = sorted(host_words(doc.url) & set(q))
    if named:
        problems.append(f"names the source ({', '.join(named)})")
    if "root cause" in " ".join(q):
        problems.append("mentions the root cause")
    return problems


# ----- prompts ----------------------------------------------------------------------------------

QUERY_SYSTEM = (
    "You write realistic incident descriptions for testing an outage search engine. "
    "Always answer with a single JSON object."
)
NEAR_DUP_SYSTEM = "You compare outage postmortems. Always answer with a single JSON object."


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."


def symptom_text(doc: DocRow) -> str:
    return _clip("\n\n".join(c.text for c in doc.other_chunks), SYMPTOM_PROMPT_CHARS)


def root_text(doc: DocRow) -> str:
    return _clip("\n\n".join(c.text for c in doc.root_cause_chunks), ROOT_PROMPT_CHARS)


def query_prompt(doc: DocRow) -> str:
    return (
        "Below is a public outage postmortem. Write the message an on-call engineer would type "
        "into an incident search tool while their own incident was still unexplained.\n\n"
        f"Postmortem title: {doc.title}\n\n"
        f"Symptom sections (what happened and who was affected):\n{symptom_text(doc)}\n\n"
        "Root cause section (for your reference only; never reveal or hint at it):\n"
        f"{root_text(doc)}\n\n"
        "Rules:\n"
        "- Describe only observable symptoms: errors, latency, which user-facing functions "
        "failed, rough scope and duration.\n"
        "- Do not state, hint at or guess the cause, and do not reuse wording from the root "
        "cause section.\n"
        "- Do not name the company, product or service, and give no dates or incident numbers.\n"
        "- Paraphrase in your own words; never copy a sentence from the postmortem.\n"
        "- One to three sentences, at most 60 words.\n"
        "- If the postmortem is not about one specific outage, or its symptoms cannot be "
        "described without revealing the cause, set usable to false.\n\n"
        'Return JSON: {"usable": true or false, "query": "<the message, empty if not usable>", '
        '"notes": "<one sentence on which symptoms you described>"}'
    )


def retry_prompt(problems: list[str]) -> str:
    return (
        "That query was rejected: "
        + "; ".join(problems)
        + ". Write a new one that follows every rule, in the same JSON format."
    )


@dataclass(frozen=True)
class NearDupCandidate:
    doc_id: int
    title: str
    url: str
    snippet: str


def near_duplicate_prompt(doc: DocRow, candidates: list[NearDupCandidate]) -> str:
    listing = "\n\n".join(
        f"[{i}] {c.title} ({c.url})\n{_clip(c.snippet, 400)}" for i, c in enumerate(candidates)
    )
    return (
        "Which candidate documents describe the same specific outage as the source document "
        "(the same incident written up again, for example by another outlet or as a follow-up)? "
        "Similar failure types or the same company on a different day do not count.\n\n"
        f"Source: {doc.title} ({doc.url})\n{_clip(symptom_text(doc), 900)}\n\n"
        f"Candidates:\n{listing}\n\n"
        'Return JSON: {"same_incident": [{"index": <candidate number>, "reason": "<why>"}]}. '
        "Use an empty list when none qualify."
    )


def parse_near_duplicates(
    data: dict[str, Any], candidates: list[NearDupCandidate]
) -> list[NearDuplicate]:
    """Suggested near-duplicates that name a real candidate; never confirmed automatically."""
    found: list[NearDuplicate] = []
    items = data.get("same_incident")
    for item in items if isinstance(items, list) else []:
        index = item.get("index") if isinstance(item, dict) else None
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(candidates)
        ):
            continue
        cand = candidates[index]
        if any(n.doc_id == cand.doc_id for n in found):
            continue
        reason = item.get("reason")
        found.append(
            NearDuplicate(
                cand.doc_id, cand.title, cand.url, reason if isinstance(reason, str) else ""
            )
        )
    return found
