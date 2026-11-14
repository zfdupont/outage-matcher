# Outage Matcher

## Overview
RAG agent: given an incident description, retrieve similar public postmortems and answer with likely cause, fix, and citations. Built with the factory plugin (milestones in `factory/milestones.md`).

## Tech Stack
- Language: Python 3.12 (uv, src/ layout)
- Framework: LangGraph, Anthropic SDK, FastAPI
- Database: Postgres + pgvector (rationale in README)

## Commands
- `uv sync` - install deps
- `uv run pytest` - tests
- `uv run ruff check . && uv run ruff format --check .` - lint
- `uv run outage-matcher --help` - CLI
- `docker compose up -d db` - start Postgres with pgvector (config in `.env`, see `.env.example`)
- `uv run outage-matcher ingest` - collect, chunk, embed and index postmortems (`--skip-collect` reuses `data/raw`)
- `uv run outage-matcher search "<query>" [--model bge|minilm] [--k 5]` - search the index (both models by default)
- `uv run outage-matcher ask "<incident description>" [--transcript PATH]` - run the agent (needs a real `ANTHROPIC_API_KEY`; model via `AGENT_MODEL`, retry cap via `AGENT_MAX_RETRIES`, API timeout seconds via `AGENT_REQUEST_TIMEOUT`, SDK retries via `AGENT_API_MAX_RETRIES`)
- `uv run outage-matcher fetch-raw` - download the manifest's pages that are missing from `data/raw` (`--strict` exits 1 unless every page is there; CI runs it on every job)
- `uv run outage-matcher serve [--host H] [--port P]` - run the API (`GET /health`, `POST /ask` runs the agent; `/ask` is 503 without a real `ANTHROPIC_API_KEY`)
- `docker compose up --build` - db plus the API container (host port `API_PORT`, default 8000)
- `uv run pytest -m db -o addopts=""` - opt-in tests that need the running Postgres container
- `uv run python evals/build_gold.py [--dry-run]` - build `evals/gold.jsonl` (needs `DEEPSEEK_API_KEY`; model via `DEEPSEEK_MODEL`)
- `uv run python -m outage_matcher.evals.run_retrieval --model bge [--chunking neighbor] [--reranker]` - recall@k and MRR to `evals/results/<run>.json`
- `uv run python evals/run_faithfulness.py [--limit N] [--dry-run]` - agent answers judged by DeepSeek (needs both API keys)
- `uv run python -m outage_matcher.evals.summary` - write `evals/results/summary.md` and `evals/baseline.json` from the result files
- `uv run python -m outage_matcher.evals.charts` - write the README figures to `docs/img/` from the result files (matplotlib is a dev dependency; rerun after `summary` when a result file changes)
- `uv run python -m outage_matcher.evals.gate index` / `compare RESULT.json` - the CI checks against `evals/baseline.json`: fail on a structurally incompatible index or a metric drop beyond the tolerance, warn on a version change alone (see `docs/ci-eval-gate.md`)
- `uv run python scripts/compare_embeddings_m1.py` - print the M1 two-model comparison tables

## Architecture
`src/outage_matcher/`: ingest (collect, chunk, embed, index), search, config, observability (`get_tracer`, `trace_span`, `flush`; no-op without Langfuse keys, see `docs/tracing.md`), agent (`tools.py`, `graph.py` LangGraph retrieve/grade/rewrite/answer with spans on each node and tool call, `transcript.py`), api (`app.py` FastAPI app taking an agent factory, `agent.py` adapter that opens one database connection per request and maps the agent result to `AskResponse`, `models.py`), evals (`gold.py`, `build_gold.py`, `metrics.py`, `retrieval.py`, `chunking.py`, `rerank.py`, `run_retrieval.py`, `faithfulness.py`, `run_faithfulness.py`, `summary.py`, `charts.py` the README figures, `gate.py` the CI regression gate). `cli.py` wires `ingest`, `fetch-raw`, `search`, `ask` and `serve` (the serve agent factory lives there). Gold set, results and baseline under `evals/` (thin entry scripts there call the modules). CI: `.github/workflows/ci.yml` (lint, format, tests) and `eval.yml` (retrieval gate, optional faithfulness job; see `docs/ci-eval-gate.md`). Docker: `Dockerfile` (multi-stage, non-root) and `docker-compose.yml` (`db`, `api`).

## Environment Variables
ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, VOYAGE_API_KEY, OPENAI_API_KEY, DATABASE_URL, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT, API_PORT, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST, AGENT_MODEL, AGENT_MAX_RETRIES, AGENT_REQUEST_TIMEOUT, AGENT_API_MAX_RETRIES (optional agent overrides; compose forwards them to the `api` service)

## Rules
- Never commit secrets or `.env`. No Co-Authored-By lines. No emojis or em-dashes. Brief commit messages.
- Every number in the README must come from a recorded run.
- Store only what is needed for local indexing; respect each source's terms.
