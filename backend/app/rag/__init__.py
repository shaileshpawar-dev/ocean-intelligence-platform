"""Retrieval-augmented research assistant."""

from app.rag.service import (
    AnswerStatus,
    ResearchAnswer,
    answer_question,
    corpus_stats,
    ingest_seed_corpus,
    search,
)

__all__ = [
    "AnswerStatus",
    "ResearchAnswer",
    "answer_question",
    "corpus_stats",
    "ingest_seed_corpus",
    "search",
]
