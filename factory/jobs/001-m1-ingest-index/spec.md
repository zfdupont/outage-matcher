# Milestone job: build every step in order, one commit per step, no separate spec.

## Conventions

- One commit per step, brief messages, no Co-Authored-By lines, no emojis or em-dashes.
- Run `commands` (test, lint, format) after the last step; all must pass.
- Tests run offline: fake the Anthropic client and embedding models; mark anything needing network or Postgres with a pytest marker and skip it by default.
- Never commit secrets or `.env`. Read config from env vars listed in `.env.example`.
- Never invent or estimate metrics. Any number written into README.md must come from a recorded run whose output is committed under `evals/results/` (or `data/` for corpus stats).
- Use `uv add` for dependencies (it updates pyproject.toml and uv.lock); keep requirements.txt and requirements-dev.txt in sync with pyproject.toml.
- A step marked `[ESCALATE: why]` stops the milestone for the owner before merge.

## M1. Ingest and index

**Goal:** a local corpus of 150-300 public postmortems, chunked by section, embedded with two models, indexed in Postgres/pgvector, searchable by CLI.

**Steps:**
1. Add `docker-compose.yml` (service `db`, image `pgvector/pgvector:pg16`, volume, healthcheck, credentials via `${...}` env references) and `src/outage_matcher/db.py` (connection from `DATABASE_URL`, schema creation: `postmortems`, `chunks` with a `vector` column per embedding model). Justify in README why pgvector over Chroma (SQL filtering by system type, one store for Ops, later deploy story).
2. Source collection `src/outage_matcher/ingest/collect.py`: build the URL list from the public community post-mortems list (danluu/post-mortems README) and cloud provider incident reports (e.g. AWS, Google Cloud status incident pages, GitHub availability reports, Cloudflare and Azure postmortems). Record each source's license/terms check in `docs/sources.md` (what is allowed, how it is used: local indexing only). Respect robots.txt, rate limit requests, identify with a generic User-Agent. Store raw HTML under `data/raw/` (git-ignored) and commit only a manifest `data/manifest.jsonl` (url, title, source, fetched date, system_type label). No Meta or employer data. Target 150 to 300 successfully parsed documents.
3. Parsing and chunking `ingest/chunk.py`: extract main text, split by headings/sections (summary, timeline, root cause, impact, remediation) with a size-capped fallback for documents without headings; tag each chunk with its section type. Unit tests with small fixture HTML.
4. Embeddings `ingest/embed.py` using fastembed (local, no API cost): `BAAI/bge-small-en-v1.5` and `sentence-transformers/all-MiniLM-L6-v2`; `ingest/index.py` writes both embedding columns with an HNSW or IVFFlat cosine index.
5. CLI `outage-matcher` (declared in pyproject `[project.scripts]`): `ingest` (collect, chunk, embed, index), `search "<query>" --model bge|minilm --k 5` printing doc title, section type, score and URL. Register in CLAUDE.md Commands.
6. Run the real ingest and record corpus stats (document count, chunk count, per-source counts, failures) in `data/corpus_stats.json`; compare the two models on 5 hand-written example queries and record the output in `docs/embedding-comparison-m1.md` (a quick qualitative check; the quantitative comparison happens in M3). Update README with the stats from that file only.

**Observable:** `docker compose up -d db && uv run outage-matcher ingest && uv run outage-matcher search "database failover caused split brain"` prints cited results from both embedding models.

