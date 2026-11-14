# Outage Matcher

RAG agent that takes a description of an incident, finds similar past outages from public postmortems, and returns a likely cause and fix with citations.

Status: scaffolding. Results are added from measured runs only.

## Setup

    uv sync
    cp .env.example .env   # fill in values

## Why pgvector over Chroma

- SQL filtering: postmortems carry a `system_type` label (database, network, storage, and so on), and retrieval can combine a vector search with a plain `WHERE system_type = ...` in one query. Chroma metadata filters cover simple equality but not joins or ad hoc SQL.
- One store for Ops: documents, chunks, both embedding columns, and later eval and trace metadata live in a single Postgres that already has backups, roles, and monitoring tooling.
- Deploy story: managed Postgres with the pgvector extension is widely available, so the local `docker compose` database and the later deployment use the same engine, instead of a separate embedded vector store to host.

Local database: `docker compose up -d db` (credentials come from `.env`, see `.env.example`).
