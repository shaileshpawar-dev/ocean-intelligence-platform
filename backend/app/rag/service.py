"""Retrieval-augmented research assistant.

The grounding contract
----------------------
Every answer this module returns is one of exactly three things, and it always
says which:

* **grounded** -- passages were retrieved and an answer is built from them,
  with a citation on every claim
* **retrieval only** -- passages were retrieved but no LLM is configured, so
  the passages are returned verbatim with citations and no synthesis
* **no evidence** -- nothing relevant was retrieved, and the assistant says so
  instead of answering from parametric memory

The third case is the one that matters. An assistant that answers marine-law
questions from a model's own weights, with no retrieved source, is the failure
mode this whole module exists to prevent. The prompt forbids it and the
no-evidence path makes it structurally impossible when the corpus is silent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.llm.base import LLMMessage
from app.llm.providers import get_llm
from app.models import ResearchChunk, ResearchDocument
from app.rag.corpus import SeedDocument, all_seed_documents
from app.rag.retrieval import BM25Index, ScoredChunk, chunk_text, rerank

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "You are a marine-environment research assistant for a satellite pollution "
    "monitoring platform.\n\n"
    "Rules you must follow exactly:\n"
    "1. Answer ONLY from the numbered passages provided. If they do not "
    "contain the answer, say so plainly and stop. Never fall back on your own "
    "knowledge.\n"
    "2. Cite the passage number in square brackets after every factual "
    "sentence, like [2].\n"
    "3. Never state that a detection proves pollution. Satellite detections "
    "are signatures with uncertainty, not confirmed incidents.\n"
    "4. Where passages are scope summaries rather than verbatim legal text, do "
    "not quote them as though they were the instrument itself.\n"
    "5. Be concise. Four sentences or fewer unless the question needs more."
)


class AnswerStatus(StrEnum):
    """How an answer was produced."""

    GROUNDED = "grounded"
    """Retrieved passages plus LLM synthesis, every claim cited."""

    RETRIEVAL_ONLY = "retrieval_only"
    """Passages retrieved; no LLM configured, so no synthesis was attempted."""

    NO_EVIDENCE = "no_evidence"
    """Nothing relevant in the corpus. The assistant declines to answer."""


@dataclass(slots=True)
class ResearchAnswer:
    """A grounded answer plus everything needed to audit it."""

    question: str
    status: AnswerStatus
    answer: str
    sources: list[dict] = field(default_factory=list)
    llm_provider: str = "none"
    llm_model: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise for the API."""
        return {
            "question": self.question,
            "status": str(self.status),
            "answer": self.answer,
            "sources": self.sources,
            "source_count": len(self.sources),
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def ingest_document(db: Session, doc: SeedDocument) -> int:
    """Store one document and its chunks. Idempotent on ``document_id``.

    Returns:
        Number of chunks written (0 if the document was already present).
    """
    existing = db.scalar(
        select(ResearchDocument).where(ResearchDocument.document_id == doc.document_id)
    )
    if existing is not None:
        return 0

    record = ResearchDocument(
        document_id=doc.document_id,
        title=doc.title,
        authors=doc.authors,
        publication=doc.publication,
        year=doc.year,
        source_url=doc.source_url,
        doc_type=doc.doc_type,
        jurisdiction=doc.jurisdiction,
        regions=doc.regions,
        topics=doc.topics,
        # The notice travels with the document so every citation can carry it.
        abstract=doc.notice,
        is_demo_fixture=False,
    )
    db.add(record)
    db.flush()

    chunks = chunk_text(doc.text)
    for index, text in enumerate(chunks):
        db.add(
            ResearchChunk(
                document_id=record.id,
                chunk_index=index,
                text=text,
                token_count=len(text.split()),
            )
        )
    return len(chunks)


def ingest_seed_corpus(db: Session) -> dict:
    """Load the seed corpus. Idempotent; safe to call on every start-up."""
    documents = all_seed_documents()
    written = sum(ingest_document(db, doc) for doc in documents)
    db.commit()

    total_docs = db.scalar(select(func.count(ResearchDocument.id))) or 0
    total_chunks = db.scalar(select(func.count(ResearchChunk.id))) or 0
    summary = {
        "seed_documents": len(documents),
        "chunks_written": written,
        "total_documents": total_docs,
        "total_chunks": total_chunks,
    }
    if written:
        logger.info("rag_corpus_ingested", extra=summary)
    return summary


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def build_index(db: Session) -> BM25Index:
    """Build a BM25 index over every stored chunk.

    Rebuilt per request. At a few hundred chunks this costs well under a
    millisecond, which is cheaper than getting cache invalidation wrong.
    """
    index = BM25Index()
    rows = db.execute(
        select(ResearchChunk, ResearchDocument).join(
            ResearchDocument, ResearchDocument.id == ResearchChunk.document_id
        )
    ).all()

    for chunk, document in rows:
        index.add(
            {
                "chunk_id": chunk.id,
                "document_id": document.document_id,
                "title": document.title,
                "text": chunk.text,
                "doc_type": document.doc_type,
                "source_url": document.source_url,
                "year": document.year,
                "publication": document.publication,
                "notice": document.abstract or "",
            }
        )
    index.finalise()
    return index


def search(
    db: Session,
    query: str,
    limit: int = 6,
    *,
    region: str | None = None,
    doc_type: str | None = None,
) -> list[ScoredChunk]:
    """Retrieve and rerank passages for ``query``."""
    index = build_index(db)
    # Over-fetch, then let the reranker choose within a wider pool.
    hits = index.search(query, limit=max(limit * 3, 12))
    if doc_type:
        hits = [h for h in hits if h.doc_type == doc_type]
    hits = rerank(
        hits,
        query,
        region=region,
        prefer_types=(doc_type,) if doc_type else (),
    )
    return hits[:limit]


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------
def answer_question(
    db: Session,
    question: str,
    *,
    limit: int = 5,
    region: str | None = None,
    doc_type: str | None = None,
) -> ResearchAnswer:
    """Answer ``question`` strictly from retrieved passages."""
    hits = search(db, question, limit=limit, region=region, doc_type=doc_type)
    sources = [_source_of(hit, position) for position, hit in enumerate(hits, 1)]

    if not hits:
        return ResearchAnswer(
            question=question,
            status=AnswerStatus.NO_EVIDENCE,
            answer=(
                "No document in the corpus addresses this question, so no "
                "answer is offered. This assistant answers only from retrieved "
                "sources and does not fall back on a language model's own "
                "knowledge. Try rephrasing with terms likely to appear in "
                "marine regulations or in this platform's methodology notes."
            ),
            notes=[
                "The seed corpus covers international and regional marine "
                "pollution instruments plus this platform's own methodology. "
                "It contains no journal literature; ingest a real corpus to "
                "extend it."
            ],
        )

    llm = get_llm()
    if not llm.is_available:
        return ResearchAnswer(
            question=question,
            status=AnswerStatus.RETRIEVAL_ONLY,
            answer=_extractive_answer(hits),
            sources=sources,
            llm_provider=llm.name,
            notes=[
                "No LLM is configured, so these are the retrieved passages "
                "verbatim rather than a synthesised answer. Set LLM_PROVIDER "
                "and the matching API key to enable synthesis. Retrieval, "
                "citations and ranking work identically either way."
            ],
        )

    context = "\n\n".join(
        f"[{position}] {hit.title}\n{hit.text}" for position, hit in enumerate(hits, 1)
    )
    response = llm.generate(
        [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=f"Passages:\n\n{context}\n\nQuestion: {question}",
            ),
        ],
        max_tokens=600,
    )

    if not response.ok:
        return ResearchAnswer(
            question=question,
            status=AnswerStatus.RETRIEVAL_ONLY,
            answer=_extractive_answer(hits),
            sources=sources,
            llm_provider=llm.name,
            notes=[
                f"LLM synthesis failed ({response.detail}). Returning the "
                "retrieved passages instead of an unsourced answer."
            ],
        )

    return ResearchAnswer(
        question=question,
        status=AnswerStatus.GROUNDED,
        answer=response.text,
        sources=sources,
        llm_provider=response.provider,
        llm_model=response.model,
        notes=[
            "Every factual sentence should carry a bracketed citation to a "
            "numbered source below. Claims without one are not supported by "
            "the retrieved corpus."
        ],
    )


def _extractive_answer(hits: list[ScoredChunk]) -> str:
    """Render retrieved passages as a citable, unsynthesised answer."""
    lines = [
        f"{len(hits)} relevant passage(s) retrieved. Shown verbatim, with "
        "sources, because no language model is configured to synthesise them:",
        "",
    ]
    for position, hit in enumerate(hits, 1):
        lines += [f"[{position}] {hit.title}", f"    {hit.text}", ""]
    return "\n".join(lines).rstrip()


def _source_of(hit: ScoredChunk, position: int) -> dict:
    """Build a citation record for one hit."""
    return {
        "position": position,
        "document_id": hit.document_id,
        "title": hit.title,
        "doc_type": hit.doc_type,
        "publication": hit.publication,
        "year": hit.year,
        "source_url": hit.source_url,
        "relevance": round(hit.score, 4),
        "matched_terms": hit.matched_terms,
        "excerpt": hit.text[:320] + ("..." if len(hit.text) > 320 else ""),
        "notice": hit.notice,
    }


def corpus_stats(db: Session) -> dict:
    """Corpus size and composition, for the API and the dashboard."""
    docs = db.scalars(select(ResearchDocument)).all()
    by_type: dict[str, int] = {}
    for doc in docs:
        by_type[doc.doc_type] = by_type.get(doc.doc_type, 0) + 1
    return {
        "documents": len(docs),
        "chunks": db.scalar(select(func.count(ResearchChunk.id))) or 0,
        "by_type": by_type,
        "retriever": "bm25-lexical",
        "reranker": "feature-based (title overlap, phrase, region, type)",
        "notes": [
            "Regulation documents carry factual metadata with "
            "platform-authored scope summaries, not verbatim legal text.",
            "Reference documents are platform-authored methodology notes.",
            "The corpus contains no journal literature; none is invented.",
        ],
    }


def new_workflow_id() -> str:
    """Generate an id for a research or agent run."""
    return uuid.uuid4().hex[:16]
