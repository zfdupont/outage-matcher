import hashlib
import sys
import types
from datetime import date

import numpy as np
import pytest

from outage_matcher import db
from outage_matcher.ingest import embed, index, stats
from outage_matcher.ingest.collect import ManifestEntry

PAGE = (
    "<html><body><article><h1>DB outage</h1><p>"
    + "The primary lost its leader and writes stopped for a while. " * 6
    + "</p><h2>Root cause</h2><p>"
    + "A partition caused split brain between two nodes. " * 6
    + "</p></article></body></html>"
)


class FakeEmbedder:
    """Deterministic 384-dim unit vectors derived from the text hash."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.calls: list[int] = []

    def _vec(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
        v = np.random.default_rng(seed).normal(size=db.EMBEDDING_DIM)
        return (v / np.linalg.norm(v)).tolist()

    def embed_documents(self, texts):
        self.calls.append(len(texts))
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(self.prefix + text)


def entry(doc_id: str, url: str, source: str = "community") -> ManifestEntry:
    return ManifestEntry(doc_id, url, f"Title {doc_id}", source, "2026-11-13", "database")


def test_models_match_db_columns_and_spec():
    assert embed.MODELS == {
        "bge": "BAAI/bge-small-en-v1.5",
        "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    }


def test_fast_embedder_uses_fastembed_and_bge_query_prefix(monkeypatch):
    seen: dict[str, object] = {}

    class FakeTextEmbedding:
        def __init__(self, model_name):
            seen["model"] = model_name

        def embed(self, texts, batch_size):
            seen.setdefault("texts", []).extend(texts)
            return (np.ones(3, dtype=np.float32) for _ in texts)

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    )
    bge = embed.FastEmbedder("bge")
    assert bge.embed_query("split brain") == [1.0, 1.0, 1.0]
    assert seen["model"] == "BAAI/bge-small-en-v1.5"
    assert seen["texts"] == [embed.QUERY_PREFIX["bge"] + "split brain"]

    seen.clear()
    minilm = embed.FastEmbedder("minilm")
    minilm.embed_query("split brain")
    assert seen["texts"] == ["split brain"]
    with pytest.raises(ValueError):
        embed.FastEmbedder("nope")


def test_embed_all_batches_and_checks_length():
    fake = FakeEmbedder()
    vectors = index.embed_all([f"t{i}" for i in range(5)], fake, batch_size=2)
    assert len(vectors) == 5 and fake.calls == [2, 2, 1]

    class Short(FakeEmbedder):
        def embed_documents(self, texts):
            return super().embed_documents(texts)[:-1]

    with pytest.raises(RuntimeError):
        index.embed_all(["a", "b"], Short())


def test_prepare_documents_reports_failures(tmp_path):
    (tmp_path / "good.html").write_text(PAGE)
    (tmp_path / "empty.html").write_text("<html><body></body></html>")
    entries = [entry("good", "u1"), entry("empty", "u2"), entry("missing", "u3")]
    docs, failures = index.prepare_documents(entries, tmp_path)
    assert [d.entry.doc_id for d in docs] == ["good"]
    assert {c.section_type for c in docs[0].chunks} == {"summary", "root_cause"}
    assert failures == [
        {"url": "u2", "reason": "no chunks extracted"},
        {"url": "u3", "reason": "raw file missing"},
    ]


def test_build_stats_counts(tmp_path):
    (tmp_path / "a.html").write_text(PAGE)
    docs, parse_failures = index.prepare_documents([entry("a", "u1", "github")], tmp_path)
    result = stats.build_stats(
        docs,
        [{"url": "x", "source": "community", "reason": "http 404"}],
        parse_failures,
        today=date(2026, 11, 13),
    )
    assert result["document_count"] == 1
    assert result["chunk_count"] == len(docs[0].chunks)
    assert result["per_source"] == {"github": {"documents": 1, "chunks": len(docs[0].chunks)}}
    assert result["failures"] == {"collect": 1, "parse": 0, "by_reason": {"http 404": 1}}
    assert result["generated"] == "2026-11-13"


@pytest.mark.db
def test_write_index_stores_both_embedding_columns(tmp_path):
    (tmp_path / "a.html").write_text(PAGE)
    docs, _ = index.prepare_documents([entry("a", "https://example.test/a")], tmp_path)
    embedders = {"bge": FakeEmbedder(), "minilm": FakeEmbedder()}
    with db.connect() as conn:
        # Everything below runs in one transaction that is rolled back, so a real index
        # in the same database is left untouched (write_index nests as a savepoint).
        conn.execute("SELECT 1")
        result = index.write_index(conn, docs, embedders)
        assert result.documents == 1 and result.chunks == len(docs[0].chunks)
        rows = conn.execute(
            "SELECT p.system_type, c.section_type, vector_dims(c.embedding_bge), "
            "vector_dims(c.embedding_minilm) FROM chunks c JOIN postmortems p "
            "ON p.id = c.postmortem_id ORDER BY c.ord"
        ).fetchall()
        assert rows == [("database", ch.section_type, 384, 384) for ch in docs[0].chunks]
        indexes = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes").fetchall()}
        assert {"chunks_bge_hnsw", "chunks_minilm_hnsw"} <= indexes
        conn.rollback()
