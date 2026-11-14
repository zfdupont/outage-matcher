"""Postgres/pgvector connection and schema."""

from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

# One vector column per embedding model. Both models emit 384-dim vectors.
EMBEDDING_COLUMNS: dict[str, str] = {
    "bge": "embedding_bge",
    "minilm": "embedding_minilm",
}
EMBEDDING_DIM = 384

SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS postmortems (
        id SERIAL PRIMARY KEY,
        url TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        source TEXT NOT NULL,
        system_type TEXT NOT NULL,
        fetched_date DATE NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS postmortems_system_type_idx ON postmortems (system_type)",
    f"""
    CREATE TABLE IF NOT EXISTS chunks (
        id SERIAL PRIMARY KEY,
        postmortem_id INTEGER NOT NULL REFERENCES postmortems (id) ON DELETE CASCADE,
        ord INTEGER NOT NULL,
        section_type TEXT NOT NULL,
        text TEXT NOT NULL,
        embedding_bge vector({EMBEDDING_DIM}),
        embedding_minilm vector({EMBEDDING_DIM}),
        UNIQUE (postmortem_id, ord)
    )
    """,
    "CREATE INDEX IF NOT EXISTS chunks_postmortem_idx ON chunks (postmortem_id)",
    "CREATE INDEX IF NOT EXISTS chunks_bge_hnsw ON chunks "
    "USING hnsw (embedding_bge vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS chunks_minilm_hnsw ON chunks "
    "USING hnsw (embedding_minilm vector_cosine_ops)",
)


def database_url() -> str:
    """Return DATABASE_URL from the environment (or a local .env file)."""
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set; copy .env.example to .env and fill it in")
    return url


def create_schema(conn: psycopg.Connection) -> None:
    """Create the extension, tables and indexes if they do not exist."""
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()


def connect(url: str | None = None, *, ensure_schema: bool = True) -> psycopg.Connection:
    """Open a connection with the pgvector adapter registered."""
    conn = psycopg.connect(url or database_url())
    if ensure_schema:
        create_schema(conn)
    register_vector(conn)
    return conn
