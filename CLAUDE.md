# Outage Matcher

## Overview
RAG agent: given an incident description, retrieve similar public postmortems and answer with likely cause, fix, and citations. Built with the factory plugin (milestones in `factory/milestones.md`).

## Tech Stack
- Language: Python 3.12 (uv, src/ layout)
- Framework: LangGraph, Anthropic SDK, FastAPI
- Database: Postgres + pgvector (or Chroma, see README)

## Commands
- `uv sync` - install deps
- `uv run pytest` - tests
- `uv run ruff check . && uv run ruff format --check .` - lint
- `uv run outage-matcher --help` - CLI

## Architecture
`src/outage_matcher/`: ingest (collect, chunk, embed, index), search, agent (LangGraph), evals, api. Eval gold set under `evals/`.

## Environment Variables
ANTHROPIC_API_KEY, VOYAGE_API_KEY, OPENAI_API_KEY, DATABASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

## Rules
- Never commit secrets or `.env`. No Co-Authored-By lines. No emojis or em-dashes. Brief commit messages.
- Every number in the README must come from a recorded run.
- Store only what is needed for local indexing; respect each source's terms.
