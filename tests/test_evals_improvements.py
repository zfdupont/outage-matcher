import json

import numpy as np
import pytest

from helpers import FakeEmbedder
from outage_matcher import db
from outage_matcher.evals import chunking, run_retrieval
from outage_matcher.evals import corpus as corpus_mod
from outage_matcher.evals.chunking import NeighborChunking, context_text
from outage_matcher.evals.corpus import ChunkRow, DocRow
from outage_matcher.evals.gold import write_gold
from outage_matcher.evals.rerank import FastEmbedReranker
from outage_matcher.evals.retrieval import Retriever, SectionChunking, build_corpus
from test_evals_retrieval import AxisEmbedder, FakeConn, gold_row, make_corpus

A, B, C = np.eye(3)


def texts_corpus():
    """Two documents of three chunks with recognisable text."""
    docs = [
        DocRow(
            d,
            f"https://x.test/{d}",
            f"Doc {d}",
            "community",
            tuple(
                ChunkRow(d * 10 + i, i, "other", f"{'d' + str(d)}-chunk{i}-" + "x" * 300)
                for i in range(3)
            ),
        )
        for d in (1, 2)
    ]
    vectors = {c.id: np.random.default_rng(c.id).normal(size=8) for doc in docs for c in doc.chunks}
    return build_corpus(docs, vectors, "bge")


# ----- reranker ---------------------------------------------------------------------------------


class ReverseReranker:
    """Scores chunks in reverse of their input order, so the reranked head is flipped."""

    name = "reverse"

    def __init__(self):
        self.seen = []

    def score(self, query, texts):
        self.seen.append(list(texts))
        return list(range(len(texts)))


def test_reranker_reorders_only_the_head_and_keeps_the_tail():
    corpus = make_corpus()
    embedder = AxisEmbedder({"q": B})
    none = np.array([], dtype=int)
    plain = Retriever(corpus, embedder).chunk_order("q", none)
    reranker = ReverseReranker()
    reranked = Retriever(corpus, embedder, reranker=reranker, rerank_depth=3).chunk_order("q", none)
    assert list(reranked[:3]) == list(plain[:3][::-1])
    assert list(reranked[3:]) == list(plain[3:])
    assert reranker.seen == [[corpus.texts[i] for i in plain[:3]]]


def test_reranker_never_sees_or_returns_excluded_chunks():
    corpus = make_corpus()
    excluded = corpus.excluded_indices(1, [2])
    reranker = ReverseReranker()
    retriever = Retriever(corpus, AxisEmbedder({"q": B}), reranker=reranker, rerank_depth=10)
    order = retriever.chunk_order("q", excluded)
    assert 2 not in order and corpus.texts[2] not in reranker.seen[0]
    assert len(order) == len(corpus.texts) - 1


def test_reranker_can_change_which_document_wins():
    corpus = make_corpus()
    none = np.array([], dtype=int)
    plain = Retriever(corpus, AxisEmbedder({"q": B})).rank_documents("q", none)
    flipped = Retriever(
        corpus, AxisEmbedder({"q": B}), reranker=ReverseReranker(), rerank_depth=7
    ).rank_documents("q", none)
    assert plain[0] == 1 and flipped[0] != 1


def test_fastembed_reranker_returns_floats_and_loads_lazily(monkeypatch):
    import fastembed.rerank.cross_encoder as ce

    made = []

    class FakeEncoder:
        def __init__(self, model_name):
            made.append(model_name)

        def rerank(self, query, documents):
            return iter(np.arange(len(documents), dtype=np.float32))

    monkeypatch.setattr(ce, "TextCrossEncoder", FakeEncoder)
    reranker = FastEmbedReranker("some/model")
    assert made == []
    assert reranker.score("q", ["a", "b"]) == [0.0, 1.0]
    reranker.score("q", ["c"])
    assert made == ["some/model"]


# ----- neighbor chunking --------------------------------------------------------------------------


def test_context_text_adds_neighbor_edges_inside_the_document_only():
    corpus = texts_corpus()
    middle = context_text(corpus, 1, frozenset(), 10)
    assert middle.startswith(corpus.texts[1])
    assert corpus.texts[0][-10:] in middle and corpus.texts[2][:10] in middle
    first = context_text(corpus, 0, frozenset(), 10)
    assert corpus.texts[1][:10] in first and "d2" not in first
    last_of_doc1 = context_text(corpus, 2, frozenset(), 10)
    assert corpus.texts[3][:10] not in last_of_doc1  # chunk 3 belongs to the next document


def test_context_text_leaves_out_held_out_neighbors():
    corpus = texts_corpus()
    text = context_text(corpus, 1, frozenset({2}), 10)
    assert corpus.texts[2][:10] not in text
    assert corpus.texts[0][-10:] in text


def test_patched_rows_re_embed_only_neighbors_of_held_out_chunks_without_their_text():
    corpus = texts_corpus()
    embedder = FakeEmbedder()
    strategy = NeighborChunking(chars=10, cache_dir=None)
    patched = strategy.patched_rows(corpus, embedder, np.array([2]))
    assert sorted(patched) == [1]  # chunk 3 starts the other document
    expected = embedder.embed_documents([context_text(corpus, 1, frozenset({2}), 10)])[0]
    assert np.allclose(patched[1], expected)
    assert strategy.patched_rows(corpus, embedder, np.array([], dtype=int)) == {}


def test_neighbor_matrix_embeds_context_and_is_cached(tmp_path):
    corpus = texts_corpus()
    embedder = FakeEmbedder()
    strategy = NeighborChunking(chars=10, cache_dir=tmp_path)
    first = strategy.matrix(corpus, embedder)
    assert first.shape[0] == len(corpus.texts)
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-5)
    plain = np.array(embedder.embed_documents(corpus.texts))
    assert not np.allclose(first[1], plain[1] / np.linalg.norm(plain[1]))
    calls = len(embedder.calls)
    second = strategy.matrix(corpus, embedder)
    assert len(embedder.calls) == calls  # served from the cache
    assert np.array_equal(first, second)


def test_neighbor_retrieval_does_not_leak_the_held_out_chunk_through_neighbors():
    corpus = texts_corpus()
    embedder = FakeEmbedder()
    strategy = NeighborChunking(chars=10, cache_dir=None)
    excluded = corpus.excluded_indices(1, [2])
    retriever = Retriever(corpus, embedder, strategy)
    # a query equal to the held-out chunk's text: the neighbor chunk 1 must not match it via
    # the (now removed) context
    query = context_text(corpus, 1, frozenset({2}), 10)
    order = retriever.chunk_order(query, excluded)
    assert 2 not in order and order[0] == 1


def test_make_chunking_knows_both_strategies_and_rejects_others():
    assert isinstance(chunking.make_chunking("section"), SectionChunking)
    assert chunking.make_chunking("neighbor", None).name == "neighbor"
    with pytest.raises(ValueError, match="unknown chunking"):
        chunking.make_chunking("windows")


# ----- run_retrieval with the options ---------------------------------------------------------


def test_main_records_reranker_and_neighbor_configuration(tmp_path, monkeypatch):
    corpus = make_corpus()
    gold_path = tmp_path / "gold.jsonl"
    write_gold([gold_row("q001", 1, "q1", [2])], gold_path)
    monkeypatch.setattr(db, "connect", lambda: FakeConn())
    monkeypatch.setattr(corpus_mod, "index_info", lambda conn: corpus_mod.IndexInfo("v1", 3, 7))
    monkeypatch.setattr(run_retrieval, "load_corpus", lambda conn, model: corpus)
    monkeypatch.setattr(run_retrieval, "get_embedder", lambda model: AxisEmbedder({"q1": B}))

    class StubReranker(ReverseReranker):
        def __init__(self, name):
            super().__init__()
            self.name = name

    monkeypatch.setattr(run_retrieval, "FastEmbedReranker", StubReranker)
    results_dir = tmp_path / "results"
    argv = ["--model", "bge", "--gold", str(gold_path), "--results-dir", str(results_dir)]
    assert run_retrieval.main([*argv, "--reranker", "org/small-ranker", "--rerank-depth", "4"]) == 0
    document = json.loads((results_dir / "bge-section-rerank-small-ranker.json").read_text())
    assert document["config"]["reranker"] == "org/small-ranker"
    assert document["config"]["rerank_depth"] == 4
    assert document["config"]["chunking_params"] == {}

    monkeypatch.setattr(
        run_retrieval, "make_chunking", lambda name, cache: NeighborChunking(cache_dir=None)
    )
    monkeypatch.setattr(
        NeighborChunking,
        "matrix",
        lambda self, corpus, embedder: corpus.embeddings,
    )
    monkeypatch.setattr(NeighborChunking, "patched_rows", lambda self, c, e, x: {})
    assert run_retrieval.main([*argv, "--chunking", "neighbor"]) == 0
    document = json.loads((results_dir / "bge-neighbor.json").read_text())
    assert document["config"]["chunking"] == "neighbor"
    assert document["config"]["chunking_params"] == {"neighbor_chars": 200}
    assert document["config"]["reranker"] is None and document["config"]["rerank_depth"] is None


def test_help_documents_chunking_and_reranker(capsys):
    with pytest.raises(SystemExit):
        run_retrieval.main(["--help"])
    out = capsys.readouterr().out
    assert "--reranker" in out and "neighbor" in out
