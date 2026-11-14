import json

import numpy as np
import pytest

from outage_matcher import db
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals import run_retrieval
from outage_matcher.evals.corpus import ChunkRow, DocRow
from outage_matcher.evals.gold import GoldQuery, NearDuplicate, write_gold
from outage_matcher.evals.retrieval import Retriever, build_corpus

# Axis vectors make every similarity hand-checkable.
A, B, C = np.eye(3)


class AxisEmbedder:
    """embed_query maps a query string to a fixed vector."""

    def __init__(self, table):
        self.table = table

    def embed_query(self, text):
        return list(self.table[text])

    def embed_documents(self, texts):
        raise AssertionError("not used")


def make_docs():
    def doc(doc_id, specs):
        chunks = tuple(
            ChunkRow(doc_id * 100 + i, i, st, f"d{doc_id}c{i}") for i, st in enumerate(specs)
        )
        return DocRow(
            doc_id, f"https://x.test/{doc_id}", f"Doc {doc_id}", "community", "net", chunks
        )

    return [
        doc(1, ["summary", "impact", "root_cause"]),
        doc(2, ["summary", "other"]),
        doc(3, ["summary", "other"]),
    ]


def make_corpus():
    docs = make_docs()
    vec = {
        100: A,  # doc 1 summary
        101: 0.5 * A + 0.5 * B,  # doc 1 impact
        102: B,  # doc 1 root cause (the held-out chunk)
        200: 0.9 * B + 0.1 * A,  # doc 2 summary
        201: C,
        300: 0.3 * B + 0.7 * C,  # doc 3 summary
        301: C,
    }
    return build_corpus(docs, vec, "bge")


def test_documents_are_ranked_by_best_chunk_once_each():
    retriever = Retriever(make_corpus(), AxisEmbedder({"q": B}))
    excluded = np.array([], dtype=int)
    # best chunk per doc: doc 1 root cause (1.0), doc 2 summary (~0.99), doc 3 summary (~0.4)
    assert retriever.rank_documents("q", excluded) == [1, 2, 3]


def test_excluding_the_held_out_chunk_moves_its_document_down():
    corpus = make_corpus()
    retriever = Retriever(corpus, AxisEmbedder({"q": B}))
    excluded = corpus.excluded_indices(1, [2])
    assert list(excluded) == [2]
    # without the root cause, doc 1 is best matched by its impact chunk (0.5 B + 0.5 A)
    assert retriever.rank_documents("q", excluded) == [2, 1, 3]
    assert 2 not in retriever.chunk_order("q", excluded)


def test_excluded_chunks_never_come_back_even_when_everything_else_is_worse():
    corpus = make_corpus()
    retriever = Retriever(corpus, AxisEmbedder({"q": B}))
    excluded = corpus.excluded_indices(1, [0, 1, 2])
    assert 1 not in retriever.rank_documents("q", excluded)


def test_stale_gold_positions_fail_loudly():
    with pytest.raises(ValueError, match="no chunks at positions"):
        make_corpus().excluded_indices(1, [7])


def gold_row(row_id, doc_id, query, ords, confirmed_near=()):
    return GoldQuery(
        id=row_id,
        query=query,
        doc_id=doc_id,
        doc_url=f"https://x.test/{doc_id}",
        doc_title=f"Doc {doc_id}",
        source="community",
        held_out_chunk_id=doc_id * 100 + ords[0],
        held_out_chunk_ids=[doc_id * 100 + o for o in ords],
        held_out_ords=ords,
        held_out_heading="Root cause",
        index_version="v1",
        generation={"model": "deepseek-flash", "temperature": 0.2, "date": "2026-11-14"},
        notes="",
        near_duplicates=[NearDuplicate(d, "t", "u", "r", confirmed=True) for d in confirmed_near],
    )


def test_evaluate_reports_the_rank_of_the_source_document_per_query():
    corpus = make_corpus()
    retriever = Retriever(corpus, AxisEmbedder({"q1": B, "q2": C}))
    gold = [gold_row("q001", 1, "q1", [2]), gold_row("q002", 3, "q2", [0])]
    results = run_retrieval.evaluate(gold, retriever)
    # q1: doc 1 loses its root cause chunk, so it ranks second behind doc 2
    # q2: doc 3's summary is held out; its other chunk (C) still ties doc 2's C chunk
    assert [r.rank for r in results][0] == 2
    assert results[1].rank in (1, 2)
    assert results[0].top_doc_ids[0] == 2


def test_confirmed_near_duplicates_count_as_relevant():
    corpus = make_corpus()
    retriever = Retriever(corpus, AxisEmbedder({"q1": B}))
    row = gold_row("q001", 1, "q1", [2], confirmed_near=[2])
    (result,) = run_retrieval.evaluate([row], retriever)
    assert result.relevant_doc_ids == [1, 2]
    assert result.rank == 1


def test_run_name_describes_the_configuration():
    assert run_retrieval.run_name("bge", "section", None) == "bge-section"
    name = run_retrieval.run_name("bge", "section", "Xenova/ms-marco-MiniLM-L-6-v2")
    assert name == "bge-section-rerank-ms-marco-minilm-l-6-v2"


def test_gold_index_mismatch_is_rejected():
    info = corpus_mod.IndexInfo("v2", 3, 7)
    with pytest.raises(ValueError, match="allow-index-mismatch"):
        run_retrieval.check_gold_matches_index([gold_row("q001", 1, "q", [2])], info)
    run_retrieval.check_gold_matches_index(
        [gold_row("q001", 1, "q", [2])], corpus_mod.IndexInfo("v1", 3, 7)
    )


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_main_writes_a_result_file_with_config_index_and_per_query_ranks(tmp_path, monkeypatch):
    corpus = make_corpus()
    gold_path = tmp_path / "gold.jsonl"
    write_gold([gold_row("q001", 1, "q1", [2]), gold_row("q002", 2, "q2", [1])], gold_path)
    monkeypatch.setattr(db, "connect", lambda: FakeConn())
    monkeypatch.setattr(corpus_mod, "index_info", lambda conn: corpus_mod.IndexInfo("v1", 3, 7))
    monkeypatch.setattr(run_retrieval, "load_corpus", lambda conn, model: corpus)
    monkeypatch.setattr(
        run_retrieval, "get_embedder", lambda model: AxisEmbedder({"q1": B, "q2": C})
    )
    results_dir = tmp_path / "results"
    argv = ["--model", "bge", "--gold", str(gold_path), "--results-dir", str(results_dir)]
    assert run_retrieval.main(argv) == 0
    document = json.loads((results_dir / "bge-section.json").read_text())
    assert document["config"]["embedding_model"] == "bge"
    assert document["config"]["chunking"] == "section"
    assert document["config"]["reranker"] is None
    assert document["index"] == {"version": "v1", "documents": 3, "chunks": 7}
    assert document["gold"]["queries"] == 2
    assert document["gold"]["generation"]["model"] == "deepseek-flash"
    assert set(document["metrics"]) == {"recall@1", "recall@3", "recall@5", "recall@10", "mrr"}
    assert [q["id"] for q in document["per_query"]] == ["q001", "q002"]
    assert all(q["rank"] is not None for q in document["per_query"])
    # a second run must not silently replace a recorded result
    assert run_retrieval.main(argv) == 1
    assert run_retrieval.main([*argv, "--force"]) == 0


def test_help_lists_the_options(capsys):
    with pytest.raises(SystemExit) as exc:
        run_retrieval.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for option in ("--model", "--chunking", "--gold", "--force"):
        assert option in out


@pytest.mark.db
def test_real_index_loads_with_unit_vectors_and_a_stable_version():
    with db.connect() as conn:
        info = corpus_mod.index_info(conn)
        assert info == corpus_mod.index_info(conn)
        corpus = run_retrieval.load_corpus(conn, "bge")
    assert len(corpus.texts) == info.chunks
    assert corpus.embeddings.shape == (info.chunks, db.EMBEDDING_DIM)
    assert np.allclose(np.linalg.norm(corpus.embeddings, axis=1), 1.0, atol=1e-4)
