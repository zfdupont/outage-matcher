import pytest

from helpers import PAGE, FakeEmbedder, entry
from outage_matcher import db
from outage_matcher.ingest import index
from outage_matcher.ingest.chunk import Chunk
from outage_matcher.ingest.collect import ManifestEntry
from outage_matcher.search import search


def test_search_validates_arguments():
    with pytest.raises(ValueError, match="unknown model"):
        search(None, "q", "nope")
    for bad_k in (0, -1, 1001):
        with pytest.raises(ValueError, match="k must"):
            search(None, "q", "bge", k=bad_k)


@pytest.mark.db
def test_search_returns_closest_chunk_per_model_and_filters(tmp_path):
    (tmp_path / "a.html").write_text(PAGE)
    docs, _ = index.prepare_documents([entry("a", "https://example.test/a")], tmp_path)
    embedders = {"bge": FakeEmbedder(), "minilm": FakeEmbedder()}
    with db.connect() as conn:
        conn.execute("SELECT 1")  # open a transaction; rolled back below, real index untouched
        index.write_index(conn, docs, embedders)
        target = docs[0].chunks[1]
        for model in db.EMBEDDING_COLUMNS:
            hits = search(conn, target.text, model, k=2, embedder=embedders[model])
            assert len(hits) == 2
            assert hits[0].url == "https://example.test/a"
            assert hits[0].section_type == target.section_type
            assert hits[0].score == pytest.approx(1.0, abs=1e-4)
            assert hits[0].score >= hits[1].score
        filtered = search(conn, "x", "bge", embedder=embedders["bge"], system_type="network")
        assert filtered == []
        conn.rollback()


def _synthetic_docs(n_database: int, n_network: int) -> list[index.PreparedDoc]:
    def doc(name: str, system_type: str, n: int) -> index.PreparedDoc:
        e = ManifestEntry(
            name, f"https://example.test/{name}", name, "community", "2026-11-13", system_type
        )
        return index.PreparedDoc(e, [Chunk(i, "other", f"{name} chunk {i}") for i in range(n)])

    return [doc("db", "database", n_database), doc("net", "network", n_network)]


@pytest.mark.db
def test_search_returns_k_rows_beyond_default_ef_search_and_for_rare_filters():
    embedders = {"bge": FakeEmbedder(), "minilm": FakeEmbedder()}
    with db.connect() as conn:
        conn.execute("SELECT 1")
        index.write_index(
            conn,
            _synthetic_docs(300, 5),
            embedders,
        )
        for model in db.EMBEDDING_COLUMNS:
            hits = search(conn, "anything", model, k=100, embedder=embedders[model])
            assert len(hits) == 100
            assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
            rare = search(
                conn, "anything", model, k=5, system_type="network", embedder=embedders[model]
            )
            assert len(rare) == 5 and {h.system_type for h in rare} == {"network"}
        conn.rollback()
