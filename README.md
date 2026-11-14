# Outage Matcher

RAG agent that takes a description of an incident, finds similar past outages from public postmortems, and returns a likely cause and fix with citations.

Status: M1 (ingest and index), M2 (agent) and M3 (evals) are built. Every number below comes from a recorded run in `evals/results/`.

## Setup

    uv sync
    cp .env.example .env   # fill in values

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

Faithfulness has not been run yet, so no faithfulness number is claimed.

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
- The faithfulness judge uses the same configurable model (`DEEPSEEK_MODEL`, default `deepseek-flash`); the exact id will be recorded in the faithfulness result file when that run happens.
