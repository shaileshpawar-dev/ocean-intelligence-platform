"""Shared response envelopes.

Every list response carries a :class:`DataProvenance` block. That is the
contract that makes the platform's honesty machine-readable rather than a
promise in a README: a client can refuse to render, or must visibly badge,
anything whose ``contains_simulated_data`` is true.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class DataProvenance(BaseModel):
    """Where the data in a response came from and how far it can be trusted."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Provider or service that produced the data.")
    contains_simulated_data: bool = Field(
        default=False,
        description=(
            "True when any record is synthetic. Clients must label such data "
            "as simulated and must never present it as an observation."
        ),
    )
    evidence_levels: list[str] = Field(
        default_factory=list,
        description="Distinct evidence levels present across the records.",
    )
    generated_at: datetime = Field(description="When this response was assembled.")
    notes: list[str] = Field(
        default_factory=list, description="Caveats that apply to the whole response."
    )


class ListResponse(BaseModel, Generic[T]):
    """Standard envelope for collection endpoints."""

    count: int
    items: list[T]
    provenance: DataProvenance


class HealthComponent(BaseModel):
    """Status of one subsystem."""

    name: str
    available: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    """Liveness and dependency status."""

    status: str
    app_name: str
    version: str
    environment: str
    demo_mode: bool
    components: list[HealthComponent]
    checked_at: datetime


class ErrorResponse(BaseModel):
    """Uniform error body."""

    error: str
    detail: str | None = None
    request_id: str | None = None
