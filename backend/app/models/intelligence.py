"""Knowledge and agentic-layer tables: documents, agent runs and reports."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import AgentRunStatus


class ResearchDocument(Base, TimestampMixin):
    """A retrievable source document for the RAG assistant.

    Only documents with a resolvable ``source_url`` or citation may be used
    to support a claim in a report. Chunks live in
    :class:`ResearchChunk` so retrieval can cite a specific passage.
    """

    __tablename__ = "research_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str | None] = mapped_column(Text)
    publication: Mapped[str | None] = mapped_column(String(256))
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    doi: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)

    # paper | regulation | report | dataset_doc
    doc_type: Mapped[str] = mapped_column(String(48), index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(128), index=True)
    regions: Mapped[list | None] = mapped_column(JSON)
    topics: Mapped[list | None] = mapped_column(JSON)

    abstract: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(128))
    is_demo_fixture: Mapped[bool] = mapped_column(default=False)


class ResearchChunk(Base):
    """A retrievable passage of a :class:`ResearchDocument`.

    The embedding is stored as a JSON float array so the default deployment
    needs no vector database. The retriever interface is written so a
    pgvector or Qdrant backend can replace this without touching callers.
    """

    __tablename__ = "research_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("research_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON)
    token_count: Mapped[int | None] = mapped_column(Integer)


class AgentRun(Base, TimestampMixin):
    """Trace of one multi-agent workflow execution.

    Records tool calls and timings, never raw chain-of-thought. What is
    persisted is a concise reasoning summary plus the evidence used, which
    is what makes a run auditable.
    """

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    workflow_name: Mapped[str] = mapped_column(String(128), index=True)

    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("pollution_events.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[str] = mapped_column(
        String(32), default=AgentRunStatus.RUNNING, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)

    llm_provider: Mapped[str | None] = mapped_column(String(48))
    llm_model: Mapped[str | None] = mapped_column(String(128))

    # [{"agent","tool","duration_ms","success","summary"}]
    steps: Mapped[list | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class Report(Base, TimestampMixin):
    """A generated Ocean Intelligence Report.

    ``sections`` holds the structured content; ``provenance`` records, for
    every claim, whether it was OBSERVED, DETECTED, INFERRED, FORECAST or
    SIMULATED, which is what the rendered report displays alongside each
    section.
    """

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("pollution_events.id", ondelete="SET NULL"), index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    sections: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict | None] = mapped_column(JSON)
    sources: Mapped[list | None] = mapped_column(JSON)

    generated_by: Mapped[str] = mapped_column(String(128))
    contains_simulated_data: Mapped[bool] = mapped_column(default=False)
