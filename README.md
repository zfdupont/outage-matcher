# Outage Matcher

RAG agent that takes a description of an incident, finds similar past outages from public postmortems, and returns a likely cause and fix with citations.

Status: M1 (ingest and index) is built. Results are added from measured runs only.

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

The qualitative comparison of the two embedding models on five hand-written queries is in `docs/embedding-comparison-m1.md`. Quantitative retrieval results come in a later milestone.
