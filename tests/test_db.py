import pytest

from outage_matcher import db


def test_schema_has_both_tables_and_one_vector_column_per_model():
    sql = " ".join(db.SCHEMA_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS postmortems" in sql
    assert "CREATE TABLE IF NOT EXISTS chunks" in sql
    for column in db.EMBEDDING_COLUMNS.values():
        assert f"{column} vector({db.EMBEDDING_DIM})" in sql
        assert f"USING hnsw ({column} vector_cosine_ops)" in sql


def test_database_url_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/d")
    assert db.database_url() == "postgresql://u:p@h:1/d"


def test_database_url_missing_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "load_dotenv", lambda: False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.database_url()


@pytest.mark.db
def test_create_schema_roundtrip():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    names = {r[0] for r in rows}
    assert {"postmortems", "chunks"} <= names
