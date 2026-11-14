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
- `uv run pytest -m "db or network" -o addopts=""` - opt-in tests that need Postgres or the network

## Architecture
`src/outage_matcher/`: ingest (collect, chunk, embed, index), search, agent (LangGraph), evals, api. Eval gold set under `evals/`.

## Environment Variables
ANTHROPIC_API_KEY, VOYAGE_API_KEY, OPENAI_API_KEY, DATABASE_URL, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

## Rules
- Never commit secrets or `.env`. No Co-Authored-By lines. No emojis or em-dashes. Brief commit messages.
- Every number in the README must come from a recorded run.
- Store only what is needed for local indexing; respect each source's terms.
