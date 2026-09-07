"""Tests for the research assistant.

The property that matters most: the assistant must not answer from a model's
own knowledge. When the corpus is silent, so is the assistant.
"""

from __future__ import annotations

import pytest
from app.rag.corpus import REFERENCES, REGULATIONS, all_seed_documents
from app.rag.retrieval import (
    BM25Index,
    ScoredChunk,
    chunk_text,
    rerank,
    tokenize,
)
from app.rag.service import (
    AnswerStatus,
    answer_question,
    corpus_stats,
    ingest_seed_corpus,
    search,
)


class TestTokenisation:
    def test_lowercases_and_drops_stopwords(self) -> None:
        assert tokenize("The Oil AND the Sea") == ["oil", "sea"]

    def test_keeps_hyphenated_and_slashed_terms_intact(self) -> None:
        """'MARPOL 73/78' and 'ship-source' are single meaningful units."""
        tokens = tokenize("MARPOL 73/78 ship-source pollution")
        assert "73/78" in tokens
        assert "ship-source" in tokens

    def test_empty_text_yields_no_tokens(self) -> None:
        assert tokenize("   ") == []


class TestChunking:
    def test_chunks_end_on_sentence_boundaries(self) -> None:
        text = " ".join(f"Sentence number {i} about marine oil." for i in range(40))
        for chunk in chunk_text(text, target_words=40):
            assert chunk.rstrip().endswith(".")

    def test_chunks_overlap_so_facts_are_not_split(self) -> None:
        text = " ".join(f"Fact {i} concerning discharge limits." for i in range(40))
        chunks = chunk_text(text, target_words=30, overlap_words=12)
        assert len(chunks) > 1
        first_words = set(chunks[0].split())
        assert first_words & set(chunks[1].split())

    def test_empty_input_yields_no_chunks(self) -> None:
        assert chunk_text("") == []


class TestBM25:
    @pytest.fixture
    def index(self) -> BM25Index:
        idx = BM25Index()
        for i, text in enumerate(
            [
                "Oil discharge from tankers is regulated under MARPOL Annex I.",
                "Plastic waste discharge into the sea is prohibited everywhere.",
                "Algal blooms cause biogenic slicks that damp capillary waves.",
            ]
        ):
            idx.add(
                {
                    "chunk_id": i,
                    "document_id": f"doc-{i}",
                    "title": f"Document {i}",
                    "text": text,
                }
            )
        idx.finalise()
        return idx

    def test_ranks_the_topical_document_first(self, index: BM25Index) -> None:
        hits = index.search("oil discharge tankers")
        assert hits[0].document_id == "doc-0"

    def test_returns_nothing_when_no_term_matches(self, index: BM25Index) -> None:
        """A zero-score hit is not a hit; padding would invite bad citations."""
        assert index.search("quantum chromodynamics") == []

    def test_reports_which_terms_matched(self, index: BM25Index) -> None:
        hits = index.search("plastic discharge")
        assert "plastic" in hits[0].matched_terms

    def test_empty_query_returns_nothing(self, index: BM25Index) -> None:
        assert index.search("the and of") == []


class TestReranking:
    """The reranker refines the lexical ordering; it does not override it.

    That is a deliberate design choice, so these assert that the signals
    raise a score -- not that they always flip a ranking, which would mean
    the feature boosts were drowning out BM25.
    """

    @staticmethod
    def _hit(title: str, text: str, index: int = 0) -> ScoredChunk:
        idx = BM25Index()
        idx.add(
            {
                "chunk_id": index,
                "document_id": f"d{index}",
                "title": title,
                "text": text,
            }
        )
        idx.finalise()
        return idx.search("oil discharge")[0]

    def test_title_overlap_raises_the_score(self) -> None:
        plain = self._hit("Unrelated Note", "oil discharge rules apply")
        titled = self._hit("Oil Discharge Regulations", "oil discharge rules apply")
        before = titled.score
        rerank([plain], "oil discharge")
        rerank([titled], "oil discharge")
        assert titled.score > before
        assert titled.score > plain.score

    def test_region_mention_raises_the_score(self) -> None:
        generic = self._hit("Note", "oil discharge occurs in open water")
        regional = self._hit("Note", "oil discharge occurs in the Persian Gulf")
        rerank([generic], "oil discharge", region="Persian Gulf")
        rerank([regional], "oil discharge", region="Persian Gulf")
        assert regional.score > generic.score

    def test_reranking_preserves_every_hit(self) -> None:
        """Reranking reorders; it must never silently drop a result."""
        hits = [
            self._hit("A", "oil discharge one"),
            self._hit("B", "oil discharge two", 1),
        ]
        assert len(rerank(hits, "oil discharge")) == 2


class TestSeedCorpus:
    def test_contains_no_invented_journal_papers(self) -> None:
        """Fabricating a bibliography is the fastest way to lose credibility."""
        assert {d.doc_type for d in all_seed_documents()} == {
            "regulation",
            "reference",
        }

    def test_every_regulation_names_a_real_body_and_source(self) -> None:
        for doc in REGULATIONS:
            assert doc.publication
            assert doc.source_url and doc.source_url.startswith("https://")

    def test_regulations_disclose_that_text_is_a_summary(self) -> None:
        for doc in REGULATIONS:
            assert "not verbatim" in doc.notice.lower()

    def test_references_are_attributed_to_the_platform(self) -> None:
        for doc in REFERENCES:
            assert "Ocean Intelligence Platform" in (doc.authors or "")
            assert "authored by the Ocean Intelligence Platform" in doc.notice


class TestIngestion:
    def test_ingest_is_idempotent(self, db) -> None:
        first = ingest_seed_corpus(db)
        second = ingest_seed_corpus(db)
        assert first["chunks_written"] > 0
        assert second["chunks_written"] == 0
        assert second["total_documents"] == first["total_documents"]

    def test_corpus_stats_describe_composition(self, db) -> None:
        ingest_seed_corpus(db)
        stats = corpus_stats(db)
        assert stats["documents"] > 0
        assert "regulation" in stats["by_type"]
        assert any("no journal literature" in n for n in stats["notes"])


class TestGroundedAnswering:
    def test_declines_when_nothing_relevant_is_retrieved(self, db) -> None:
        """The central guarantee: silence rather than parametric recall."""
        ingest_seed_corpus(db)
        result = answer_question(db, "What is the airspeed of a swallow?")
        assert result.status is AnswerStatus.NO_EVIDENCE
        assert result.sources == []
        assert "does not fall back" in result.answer

    def test_retrieval_only_without_an_llm(self, db) -> None:
        ingest_seed_corpus(db)
        result = answer_question(db, "oil discharge from ships regulation")
        assert result.status is AnswerStatus.RETRIEVAL_ONLY
        assert result.sources
        assert result.llm_provider == "none"

    def test_every_source_is_citable(self, db) -> None:
        ingest_seed_corpus(db)
        result = answer_question(db, "MARPOL oil discharge special areas")
        for source in result.sources:
            assert source["title"]
            assert source["position"] >= 1
            assert source["document_id"]

    def test_sources_carry_their_summary_notice(self, db) -> None:
        """A reader must never mistake a scope summary for treaty text."""
        ingest_seed_corpus(db)
        result = answer_question(db, "MARPOL oil discharge special areas")
        assert any(s["notice"] for s in result.sources)

    def test_region_relevant_query_finds_the_regional_instrument(self, db) -> None:
        ingest_seed_corpus(db)
        hits = search(db, "Persian Gulf oil pollution regional convention")
        assert any("ROPME" in h.title or "Kuwait" in h.title for h in hits)

    def test_doc_type_filter_restricts_results(self, db) -> None:
        ingest_seed_corpus(db)
        hits = search(db, "oil detection method", doc_type="reference")
        assert hits
        assert all(h.doc_type == "reference" for h in hits)
