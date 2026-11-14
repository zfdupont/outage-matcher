import pytest

from helpers import PAGE, FakeEmbedder, entry
from outage_matcher import db
from outage_matcher.ingest import index
from outage_matcher.search import search


def test_search_validates_arguments():
    with pytest.raises(ValueError, match="unknown model"):
        search(None, "q", "nope")
    with pytest.raises(ValueError, match="k must"):
        search(None, "q", "bge", k=0)


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
