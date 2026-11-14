# Outage Matcher

RAG agent that takes a description of an incident, finds similar past outages from public postmortems, and returns a likely cause and fix with citations.

Status: M1 (ingest and index), M2 (agent), M3 (evals) and M4 (API, tracing, CI gate) are built. Every number below comes from a recorded run in `evals/results/`.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and Docker. Python 3.12 is installed by uv.

    uv sync
    cp .env.example .env             # fill in values, see below
    docker compose up -d db          # Postgres with pgvector
    uv run outage-matcher ingest     # collect, chunk, embed, index (minutes; downloads two local models)
    uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers"
    docker compose up --build        # the API: http://localhost:8000/health and POST /ask

Values in `.env` (placeholders in `.env.example`, never commit `.env`):

- `ANTHROPIC_API_KEY`: the agent (`ask`, `serve`, the faithfulness eval). Without a real key `serve` still starts and `POST /ask` answers 503.
- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`: building the gold set and the faithfulness judge only.
- `POSTGRES_*`, `DATABASE_URL`, `API_PORT`: the database and the published API port. For `uv run` use `DATABASE_URL` with host `localhost`; compose rewrites it to the `db` host inside the network.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`: optional tracing, see `docs/tracing.md`.
- `AGENT_MODEL`, `AGENT_MAX_RETRIES`, `AGENT_REQUEST_TIMEOUT`, `AGENT_API_MAX_RETRIES`: optional agent overrides.

## Architecture

    public postmortems (URLs in data/manifest.jsonl)
            |  outage-matcher ingest  (collect -> chunk by section -> embed with bge + minilm)
            v
    Postgres + pgvector  <----------------------------------------------+
    (postmortems, chunks, HNSW cosine index per model)                   |
            ^                                                            |
            |  search_incidents / get_postmortem / filter_by_system_type |
            |                                                            |
    LangGraph agent  (src/outage_matcher/agent)                          |
      retrieve --> grade --relevant--> answer --> likely cause, fix, citations
         ^           |                                                   |
         +-- rewrite +--none relevant, retries left                      |
            ^                                                            |
            |  OutageAgent.ask(question)                                 |
    FastAPI  (src/outage_matcher/api)        CLI ask / serve             |
      GET /health, POST /ask  <---- Docker image, compose `api` service  |
            |                                                            |
            +--> Langfuse (optional): a trace per question, spans per node and tool call

    Evals (src/outage_matcher/evals, evals/): gold set -> retrieval recall@k and MRR, faithfulness
    judge, summary and baseline -> CI gate (.github/workflows/eval.yml) fails on a regression.

## Commands

    uv run pytest -q                                   # tests (offline; -m db for Postgres tests)
    uv run ruff check . && uv run ruff format --check .
    uv run outage-matcher ingest [--skip-collect]      # build the index
    uv run outage-matcher fetch-raw                    # download the manifest's pages into data/raw
    uv run outage-matcher search "<query>" [--model bge|minilm] [--k 5]
    uv run outage-matcher ask "<incident>" [--transcript PATH]
    uv run outage-matcher serve [--host H] [--port P]  # the API without Docker
    docker compose up --build                          # db and API
    uv run python -m outage_matcher.evals.gate index   # CI gate checks, see docs/ci-eval-gate.md
    uv run python -m outage_matcher.evals.gate compare RESULT.json

The eval commands are listed under Evals (M3).

## API (M4)

    curl -s localhost:8000/health
    curl -s -X POST localhost:8000/ask -H 'content-type: application/json' \
      -d '{"question": "checkout latency spiked after a config push to our load balancers"}'

`POST /ask` runs the LangGraph agent and returns `answer`, `likely_cause`, `suggested_fix` and
`citations` (doc id, title, URL, section). Each request opens its own database connection. Errors are
JSON `{"error": {"status", "message"}}` without stack traces: 422 for a bad body, 503 when there is
no API key or the search backend is down, 502 when the model API call fails. A real request through
the container is recorded in `docs/compose-ask-example.md`.

## Tracing (M4)

With `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` set, each question becomes a Langfuse trace
with a span per graph node and per tool call. Without them tracing is a no-op. Details, and what
has and has not been verified, are in `docs/tracing.md`.

## CI eval gate (M4)

`.github/workflows/eval.yml` builds the index in CI from the committed manifest (caching `data/raw`
keyed on the manifest hash, fetching only on a cache miss), runs the retrieval eval and compares it
with `evals/baseline.json`. The rule:

- The job fails, with a message to refresh the baseline, only if the fresh index is structurally
  incompatible with the gold set: a gold held-out chunk id or relevant document id is missing, or the
  document or chunk count is more than 2 percent from the baseline's.
- Otherwise it fails when recall@k or MRR is more than the tolerance (0.05, absolute) below the
  baseline.
- A different index version alone (for example a forum page's view counter changed) only prints a
  `WARNING` with the old and new version; the job still passes if the metrics are within tolerance.

The LLM-judged faithfulness job runs only on manual dispatch or when both API-key secrets exist. The
workflow has not been run on GitHub; the comparison logic is `outage_matcher.evals.gate`, covered by
unit tests. See `docs/ci-eval-gate.md`.

## Why pgvector over Chroma

- SQL filtering: postmortems carry a `system_type` label (database, network, storage, and so on), and retrieval can combine a vector search with a plain `WHERE system_type = ...` in one query. Chroma metadata filters cover simple equality but not joins or ad hoc SQL.
- One store for Ops: documents, chunks, both embedding columns, and later eval and trace metadata live in a single Postgres that already has backups, roles, and monitoring tooling.
- Deploy story: managed Postgres with the pgvector extension is widely available, so the local `docker compose` database and the later deployment use the same engine, instead of a separate embedded vector store to host.

Local database: `docker compose up -d db` (credentials come from `.env`, see `.env.example`).

## Ingest and search (M1)

    docker compose up -d db
    uv run outage-matcher ingest
    uv run outage-matcher search "database failover caused split brain" --k 5

`ingest` collects public postmortems (see `docs/sources.md` for what is fetched and the terms checks),
splits them into section-typed chunks, embeds each chunk with two local fastembed models
(`BAAI/bge-small-en-v1.5` and `sentence-transformers/all-MiniLM-L6-v2`) and writes both vectors to
Postgres with an HNSW cosine index per model. `search` prints results from both models unless `--model bge|minilm` is given.
Raw pages stay local under `data/raw/` (git-ignored); the committed `data/manifest.jsonl` lists only URL, title, source, fetch date and a heuristic system-type label.

### Corpus

Numbers below are copied from `data/corpus_stats.json` (generated 2026-11-13).

- Documents: 235. Chunks: 4482.
- Per source (documents / chunks): cloudflare 29 / 584, community 103 / 1896, gcp 22 / 866, github 81 / 1136.
- Candidate pages that were not stored: 99 at collection (49 denied hosts, 21 too little text, 17 page-level robots meta, 4 robots.txt, 4 HTTP 404, 2 HTTP 403, 1 robots.txt fetch failed, 1 too large) and 1 with no extractable chunks.
- Chunks by section type: impact 756, other 2422, remediation 212, root_cause 133, summary 838, timeline 121.

The qualitative comparison of the two embedding models on five hand-written queries is in `docs/embedding-comparison-m1.md`. Quantitative retrieval results are in the Results section below.

## Agent (M2)

    uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers"

Needs a real `ANTHROPIC_API_KEY` and a loaded index. A LangGraph graph runs `retrieve` (the model calls
`search_incidents`, `get_postmortem` and `filter_by_system_type` through Anthropic tool use), `grade`
(the model marks each retrieved chunk relevant or not), then either `rewrite` (new query, retry counter
plus one, capped by `AGENT_MAX_RETRIES`, default 2) or `answer`. The answer gives a likely cause, a
suggested fix and citations; a citation of a document that was not retrieved is dropped, and with no
relevant retrieval after the cap the agent says there is no close match. The model defaults to
`claude-haiku-5-5` (`AGENT_MODEL` overrides). Each run prints token usage; `--transcript PATH` saves a
Markdown transcript (see `docs/examples/`).

## Evals (M3)

    uv run python evals/build_gold.py                         # gold set, needs DEEPSEEK_API_KEY
    uv run python evals/run_retrieval.py --model bge          # also --chunking neighbor, --reranker
    uv run python evals/run_faithfulness.py                   # needs ANTHROPIC_API_KEY and DEEPSEEK_API_KEY
    uv run python -m outage_matcher.evals.summary             # evals/results/summary.md, evals/baseline.json

- Gold set (`evals/gold.jsonl`): for each postmortem with a clear root-cause section, that section is
  held out (its chunks are excluded from retrieval for that query) and a DeepSeek model writes a
  symptoms-only query from the remaining sections. Queries that copy long runs of words from the
  postmortem, or name its source, are rejected and regenerated. The model id, temperature, date and
  index version are stored with every query. The source document is the relevant document; near-duplicates
  the model suggests are stored unconfirmed and only count once a person sets `confirmed` by hand.
- Retrieval metrics (`src/outage_matcher/evals/metrics.py`): recall@k for k in 1, 3, 5, 10 and MRR over
  document ranks. A document sits where its best chunk does. Retrieval is exact cosine similarity
  over all chunk vectors, so held-out chunks can be excluded per query.
- Improvements: a local cross-encoder reranker (`Xenova/ms-marco-MiniLM-L-6-v2` through fastembed, top 50
  chunks reranked) and neighbor chunking (each chunk embedded with 200 characters from each adjacent
  chunk; a held-out chunk is also removed from its neighbors' context for that query).
- Faithfulness (`run_faithfulness.py`): the agent answers every gold query with the held-out chunks hidden
  from its tools, then a DeepSeek judge at temperature 0 splits the answer into claims and marks each
  as supported or not by the cited chunks. The judge is a different model family from the Anthropic
  agent, so it does not grade its own family's output. The judge prompt, model and temperature are
  recorded in the result file.
- `evals/baseline.json` holds the baseline run's metrics and a stated tolerance for the M4 regression gate.

## Results

Copied from `evals/results/summary.md`. Gold set: 34 synthetic queries, one index (235 documents, 4482
chunks). Rank is the position of the source document among distinct documents.

### Embedding models (section chunking)

| Model | recall@1 | recall@3 | recall@5 | recall@10 | MRR |
| --- | --- | --- | --- | --- | --- |
| bge (BAAI/bge-small-en-v1.5) | 0.412 | 0.588 | 0.647 | 0.735 | 0.519 |
| minilm (sentence-transformers/all-MiniLM-L6-v2) | 0.265 | 0.412 | 0.559 | 0.765 | 0.391 |

Baseline: **bge, section chunking** (highest MRR of the models above).

### Improvements on the identical gold set

| Configuration | recall@1 | recall@3 | recall@5 | recall@10 | MRR | vs baseline MRR | better / worse / same queries |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bge, section chunking | 0.412 | 0.588 | 0.647 | 0.735 | 0.519 | baseline | - |
| bge, neighbor chunking | 0.412 | 0.559 | 0.618 | 0.706 | 0.515 | -0.005 | 6 / 15 / 13 |
| bge, section chunking, rerank Xenova/ms-marco-MiniLM-L-6-v2 (top 50) | 0.588 | 0.676 | 0.735 | 0.765 | 0.646 | +0.127 | 10 / 5 / 19 |

### Faithfulness (LLM judge)

- Agent: claude-haiku-5-5 (Anthropic). Judge: deepseek-flash (DeepSeek, a different model family), temperature 0.0. Run on 2026-11-13. A single run of a nondeterministic agent.
- Queries: 34; judged answers: 27; abstained (no close match): 7; errors: 0. The rates below cover only the 27 judged answers; abstentions are not scored.
- Abstentions: 0 of 7 followed citations that were all dropped by the citation check (a cited document that was not retrieved); 5 had relevant chunks but no valid citation or text (q006, q009, q027, q029, q032), cause not explained; 2 had no relevant retrieval.
- Claims supported by the cited chunks: 239 of 336 (0.711).
- Answers with every claim supported: 0.037.
- Tokens: agent 376959 in / 34754 out, judge 22753 in / 17458 out.

#### Before and after the citation-prompt fix

Every row is one run on the same gold set, index and judge; the agent is nondeterministic, so each row is a single draw. 2 runs were made with the earlier answer prompt, which listed excerpts as `[0] doc_id=...`; the model often cited the position instead of the doc_id and the citation check turned those answers into abstentions. The current run labels excerpts by doc_id only.

| Run | answers judged | abstained | claims supported | claim support | answers with every claim supported |
| --- | --- | --- | --- | --- | --- |
| before the fix, first run (2026-11-13) | 15 of 34 | 19 | 125 of 183 | 0.683 | 0.067 |
| before the fix, second run (2026-11-13) | 19 of 34 | 15 | 147 of 219 | 0.671 | 0.000 |
| after the fix (2026-11-13) | 27 of 34 | 7 | 239 of 336 | 0.711 | 0.037 |

The answered sets differ in size (15, 19, 27 answers), and abstentions are excluded from the rates, so the rates are not like-for-like.

Differences in claim support and in all-claims-supported between the earlier runs and the current one (claim support 0.671 to 0.683 before, 0.711 after; all-claims-supported 0.000 to 0.067 before, 0.037 after) are within the run-to-run noise of single nondeterministic runs; the earlier runs alone abstained on 15 to 19 queries.

The only clear effect of the fix is fewer abstentions: the abstentions after dropped citations were 11 of 15 in `faithfulness-prefix-bug.json` before the fix and 0 of 7 after it. Runs without per-answer notes cannot be counted.

Reading these numbers: faithfulness here means each claim is supported by the chunks the answer
cites; it is not correctness against the held-out root cause. The judge is strict, so generic advice
that no excerpt mentions counts as unsupported, which is why almost no answer has every claim
supported. The judge ran with `thinking` disabled so that temperature 0 applies (set in the DeepSeek
client; the faithfulness result files recorded so far predate the `judge_thinking` config field and
do not list it).

The first runs exposed an agent bug: the answer prompt listed excerpts as `[0] doc_id=...`, the model
cited those positions, the citation check dropped them and the agent abstained. The prompt now labels
excerpts by doc_id only (the citation check is unchanged). Three runs exist: two before the fix and
one after, all single draws of a nondeterministic agent. Two runs with the same buggy prompt
abstained on 19 and 15 queries, so the differences in claim support and in all-claims-supported
between the runs are within noise. The only clear effect of the fix is fewer abstentions. Five
abstentions after the fix (q006, q009, q027, q029, q032) are unexplained: the grader accepted chunks
but the answer had no valid citation or text, and they were not investigated. The 27 judged answers
are therefore not the agent's ceiling, and the rates describe judged answers only.

### Limitations

- The queries are synthetic: a language model (`deepseek-flash`, the model id recorded in `evals/gold.jsonl`)
  wrote each from the same postmortem's non-root-cause sections, so they share more vocabulary with their
  source document than a real on-call description would. Absolute scores say little about real incidents;
  the comparison between configurations on identical queries is the useful part.
- With 34 queries, one query moves recall@k by 0.029. The embedding model and the improvements were
  chosen and measured on the same gold set, with no separate held-out test set, so the improvement
  figures are optimistic by an unknown amount.
- Only chunks classified as `root_cause` are held out. Other sections can still describe the cause, and
  suggested near-duplicate documents are not confirmed, so they do not count as relevant.
- The faithfulness judge is `deepseek-flash` (id recorded in `evals/results/faithfulness.json`), the same model family that wrote the gold queries, with `thinking` disabled and temperature 0. It is a different family from the Anthropic agent, but a model judging claims is still an imperfect measure.
