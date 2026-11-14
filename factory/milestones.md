# Milestones

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

## M2. Agent

**Goal:** a LangGraph agent that retrieves, grades, rewrites and retries, then answers with citations, using real Anthropic tool use.

**Steps:**
1. Add dependencies `langgraph` and `anthropic`. Config in `src/outage_matcher/config.py`: model name default `claude-haiku-5-5` (override by env `AGENT_MODEL`), max retries default 2.
2. Tools in `agent/tools.py` with JSON-schema definitions and implementations over the index: `search_incidents(query, k, system_type?)`, `get_postmortem(doc_id)`, `filter_by_system_type(system_type, query?)`. Tool errors return structured error results, never raise into the loop.
3. Graph in `agent/graph.py` with explicit state: `retrieve` node (the LLM chooses and calls tools via the Anthropic Messages API tool-use loop), `grade` node (LLM grades each retrieved chunk relevant or not, structured output), conditional edge to `rewrite` (LLM rewrites the query, increments the retry counter, hard cap) or `answer`, and `answer` node producing likely cause, suggested fix and citations referencing only retrieved doc ids. Empty or irrelevant retrieval after the cap yields an honest "no close match" answer.
4. Tests with a fake Anthropic client covering: tool call dispatch, malformed tool args, retry cap termination, citation validation (answer cannot cite an id that was not retrieved), no-match path.
5. CLI `outage-matcher ask "<incident description>"` printing the answer and citations; print token usage per run. Do a few real runs (requires `ANTHROPIC_API_KEY`; if it is not set in the environment or `.env`, stop with a clear note instead of failing) and save 3 example transcripts to `docs/examples/`.

**Observable:** `uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers"` returns a likely cause and fix citing real indexed postmortems.

## M3. Evals

**Goal:** a labeled gold set, retrieval and faithfulness metrics, and a measured baseline vs. improvement comparison.

**Steps:**
1. `evals/build_gold.py` creates about 40 gold queries: pick postmortems with a clear root-cause section; hold that section out of the index for the query (exclude from retrieval during eval) and use an LLM (Anthropic API, cheap model) to write a symptoms-only query that does not use the root-cause wording; label the source doc as relevant and manually-checkable near-duplicates when the LLM suggests them. Save `evals/gold.jsonl` with doc ids, the held-out chunk id and generation notes. Record the generation model and date.
2. `src/outage_matcher/evals/metrics.py`: recall@k (k=1,3,5,10) and MRR with unit tests on hand-checkable cases; `evals/run_retrieval.py` computes them for a given embedding model, chunking strategy and optional reranker, writing `evals/results/<run-name>.json` (config, date, index version, per-query ranks).
3. Compare the two embedding models on the gold set (baseline = section chunking with the better of the two). Add one improvement and measure it on the identical gold set: a reranker (a local cross-encoder via fastembed or an LLM rerank) or an alternative chunking strategy (e.g. section-plus-neighbor context, or fixed windows). Record both runs in `evals/results/`.
4. LLM-as-judge faithfulness `evals/run_faithfulness.py`: run the agent on every gold query; a judge model scores whether each claim in the answer is supported by the cited chunks (record judge prompt, model, temperature in the result). Keep API cost to a few dollars; print estimated and actual token usage.
5. Write `evals/results/summary.md` generated from the result files (table baseline vs. improvement) and add the committed baseline file used for regression checks in M4 (`evals/baseline.json`) with a stated tolerance.
6. README gains a Results section whose every number is copied from `evals/results/summary.md`. Include the limitation that queries are synthetic.

**Observable:** `uv run python -m outage_matcher.evals.run_retrieval --help` and the committed results show recall@k and MRR for each configuration.

## M2b. Ops skeleton

**Goal:** the deployable shell around the agent, built in parallel with M2 on files M2 does not touch (api/, observability.py, Dockerfile, compose api service, CI lint/test workflow). Do not touch `src/outage_matcher/agent/`, `config.py` or ingest code.

**Steps:**
1. Add `fastapi`, `uvicorn` and `langfuse` with `uv add`. Define in `src/outage_matcher/api/models.py` the typed `AskRequest` and `AskResponse` (answer, likely_cause, suggested_fix, citations with doc id, title, url, section) and in `api/app.py` a `Protocol` `Agent` with `ask(question) -> AskResponse`; the app takes an agent factory so tests inject a fake. `POST /ask`, `GET /health`, errors as JSON with proper status codes and no stack traces. Until M4 wires the real agent, a missing agent returns 503. Tests with TestClient. CLI `outage-matcher serve`.
2. `src/outage_matcher/observability.py`: `get_tracer()` returns a Langfuse callback handler when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, else None (no-op), with tests for both cases and a `trace_span` helper usable as a decorator.
3. `Dockerfile` multi-stage with uv, non-root user, `HEALTHCHECK` hitting `/health`; extend `docker-compose.yml` with an `api` service (env via `${...}` references, depends_on db healthy). Build the image and run the container with the db, confirm the healthcheck turns healthy and `GET /health` answers.
4. `.github/workflows/ci.yml`: lint, format check and tests on pull requests and pushes with uv; no secrets needed. (The eval gate comes in M4.)

**Observable:** `docker compose up --build` serves `GET /health`; `POST /ask` returns 503 until the agent is wired.

## M4. Ops

**Goal:** wire everything together: real agent in the API, Langfuse tracing of each agent step, CI eval gate. Depends on M2, M2b and M3 being merged.

**Steps:**
1. Wire the LangGraph agent into the API factory (`POST /ask` calls the real agent) and the `serve` command; keep the fake-agent tests.
2. Langfuse tracing: use `observability.get_tracer()` as a callback on the graph and wrap each tool call and node in a span; tracing stays a no-op when keys are unset; test the agent with tracing disabled.
3. `.github/workflows/eval.yml`: on pull requests start a pgvector service container, run ingest from the manifest, run the retrieval eval and compare with `evals/baseline.json`, failing the job when recall@k or MRR drops beyond the tolerance. The LLM-judged faithfulness job runs only on `workflow_dispatch` or when the `ANTHROPIC_API_KEY` secret is present. Secrets come only from GitHub secrets. `[ESCALATE: CI workflow that handles secrets, owner should read it before merge]`
4. Update README (setup, text architecture diagram, commands, results section kept from M3), CLAUDE.md Architecture to match the final layout, and a short tracing note under `docs/`. Run `docker compose up --build` once more with the real agent and confirm `/health` and a `/ask` request (needs the API key).

**Observable:** `docker compose up --build` serves `POST /ask` and `GET /health`; Langfuse shows a trace per agent step when keys are configured.
