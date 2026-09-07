"""Tools the agents may call.

Every tool is a thin wrapper over a service that already exists and is already
tested. That is deliberate: an agent layer whose tools contain their own
business logic is a second implementation of the system that can drift from
the first. Here the agents can only reach the same risk engine, the same
forecaster and the same retriever that the REST API uses, so an agent's
answer and an API response can never disagree.

Tool calls are timed and recorded on the :class:`~app.models.AgentRun`, which
is what makes a workflow auditable after the fact.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import PollutionEvent, Region

logger = get_logger(__name__)


@dataclass(slots=True)
class ToolCall:
    """A record of one tool invocation."""

    tool: str
    arguments: dict[str, Any]
    duration_ms: float
    success: bool
    summary: str
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialise for the agent-run trace."""
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "summary": self.summary,
            "error": self.error,
        }


@dataclass(slots=True)
class Tool:
    """A callable an agent may use."""

    name: str
    description: str
    func: Callable[..., Any]

    def __call__(self, **kwargs: Any) -> tuple[Any, ToolCall]:
        """Invoke the tool, returning its result and a call record."""
        started = time.perf_counter()
        try:
            result = self.func(**kwargs)
            duration = (time.perf_counter() - started) * 1000
            return result, ToolCall(
                tool=self.name,
                arguments={k: _brief(v) for k, v in kwargs.items()},
                duration_ms=duration,
                success=True,
                summary=_summarise(result),
            )
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            logger.warning("tool_failed", extra={"tool": self.name})
            return None, ToolCall(
                tool=self.name,
                arguments={k: _brief(v) for k, v in kwargs.items()},
                duration_ms=duration,
                success=False,
                summary="failed",
                error=f"{type(exc).__name__}: {exc}",
            )


def _brief(value: Any) -> Any:
    """Shorten an argument for the trace, and never log a Session."""
    if isinstance(value, Session):
        return "<session>"
    if isinstance(value, str) and len(value) > 120:
        return value[:120] + "..."
    return value


def _summarise(result: Any) -> str:
    """One-line description of a tool result, for the trace."""
    if result is None:
        return "no result"
    if isinstance(result, dict):
        return f"dict with {len(result)} keys"
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    return type(result).__name__


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def get_pollution_event(db: Session, event_id: str) -> dict | None:
    """Fetch one detection with its risk breakdown and source measurement."""
    from app.services.pollution_service import get_event

    return get_event(db, event_id)


def get_pollution_history(db: Session, region_code: str, days: int = 60) -> dict:
    """Daily activity series for a region, with observed coverage."""
    from app.services.analytics_service import get_trends

    for trend in get_trends(db, days=days):
        if trend.region_code == region_code:
            return trend.to_dict()
    return {
        "region_code": region_code,
        "series": [],
        "coverage_days": 0,
        "window_days": days,
        "detail": "No stored history for this region.",
    }


def get_forecast(db: Session, region_code: str, horizon: int = 7) -> dict:
    """Forecast detection activity, including whether it beat the baseline."""
    from app.services import forecast_service

    result = forecast_service.forecast_region(db, region_code, horizon=horizon)
    payload = result.to_dict()
    payload["bands"] = forecast_service.forecast_to_severity_bands(result)
    return payload


def get_geographic_context(latitude: float, longitude: float) -> dict:
    """Coarse coastline and protected-area proximity, with precision notes."""
    from app.risk.geo import get_geographic_provider

    geo = get_geographic_provider()
    coast = geo.distance_to_coast(latitude, longitude)
    mpa = geo.nearest_protected_area(latitude, longitude)
    return {
        "distance_to_coast_km": coast.distance_km,
        "nearest_coastal_reference": coast.nearest_name,
        "coast_precision_note": coast.precision_note,
        "nearest_protected_area": mpa.nearest_name,
        "distance_to_protected_area_km": mpa.distance_km,
        "protected_area_precision_note": mpa.precision_note,
    }


def calculate_risk(
    signature: str,
    confidence: float,
    latitude: float | None = None,
    longitude: float | None = None,
    estimated_area_km2: float | None = None,
    trend_slope: float | None = None,
) -> dict:
    """Score risk with the deterministic engine.

    This is the only path to a risk number anywhere in the agent layer. No
    agent may produce a score itself, and no prompt asks a model for one.
    """
    from app.risk.engine import get_risk_engine

    return (
        get_risk_engine()
        .assess(
            signature=signature,
            confidence=confidence,
            latitude=latitude,
            longitude=longitude,
            estimated_area_km2=estimated_area_km2,
            trend_slope=trend_slope,
        )
        .to_dict()
    )


def search_research(db: Session, query: str, limit: int = 4) -> list[dict]:
    """Retrieve supporting passages from the research corpus."""
    from app.rag.service import search

    return [hit.to_dict() for hit in search(db, query, limit=limit)]


def get_satellite_observation(db: Session, event_id: str) -> dict | None:
    """The measurement behind a detection."""
    event = db.scalar(select(PollutionEvent).where(PollutionEvent.event_id == event_id))
    if event is None or event.observation is None:
        return None
    obs = event.observation
    return {
        "observation_id": obs.observation_id,
        "collection": obs.collection,
        "platform": obs.platform,
        "acquired_at": obs.acquired_at.isoformat(),
        "mean_db": obs.mean_db,
        "p10_db": obs.p10_db,
        "p90_db": obs.p90_db,
        "contrast_db": (
            round(obs.p90_db - obs.p10_db, 2)
            if obs.p90_db is not None and obs.p10_db is not None
            else None
        ),
        "evidence_level": obs.evidence_level,
    }


def get_region(db: Session, region_code: str) -> dict | None:
    """Region metadata including its stored geographic context."""
    region = db.scalar(select(Region).where(Region.code == region_code))
    if region is None:
        return None
    return {
        "code": region.code,
        "name": region.name,
        "parent_region": region.parent_code,
        "centroid": [region.centroid_lat, region.centroid_lon],
        "bbox": [region.min_lon, region.min_lat, region.max_lon, region.max_lat],
        "distance_to_coast_km": region.distance_to_coast_km,
        "nearest_protected_area": region.nearest_protected_area,
        "distance_to_protected_area_km": region.distance_to_protected_area_km,
    }


@dataclass(slots=True)
class ToolRegistry:
    """The tools available to a workflow, bound to a session."""

    db: Session
    calls: list[ToolCall] = field(default_factory=list)

    def _tools(self) -> dict[str, Tool]:
        return {
            "get_pollution_event": Tool(
                "get_pollution_event",
                "Fetch a detection with its risk breakdown and measurement.",
                lambda **kw: get_pollution_event(self.db, **kw),
            ),
            "get_pollution_history": Tool(
                "get_pollution_history",
                "Daily activity series for a region over a window.",
                lambda **kw: get_pollution_history(self.db, **kw),
            ),
            "get_forecast": Tool(
                "get_forecast",
                "Forecast detection activity with prediction intervals.",
                lambda **kw: get_forecast(self.db, **kw),
            ),
            "get_geographic_context": Tool(
                "get_geographic_context",
                "Coastline and protected-area proximity for a coordinate.",
                get_geographic_context,
            ),
            "calculate_risk": Tool(
                "calculate_risk",
                "Deterministic risk score with per-factor contributions.",
                calculate_risk,
            ),
            "search_research": Tool(
                "search_research",
                "Retrieve passages from the regulatory/methodology corpus.",
                lambda **kw: search_research(self.db, **kw),
            ),
            "get_satellite_observation": Tool(
                "get_satellite_observation",
                "The backscatter measurement behind a detection.",
                lambda **kw: get_satellite_observation(self.db, **kw),
            ),
            "get_region": Tool(
                "get_region",
                "Region metadata and stored geographic context.",
                lambda **kw: get_region(self.db, **kw),
            ),
        }

    def call(self, name: str, **kwargs: Any) -> Any:
        """Invoke a tool by name, recording the call on this run."""
        tool = self._tools().get(name)
        if tool is None:
            self.calls.append(
                ToolCall(
                    tool=name,
                    arguments={},
                    duration_ms=0.0,
                    success=False,
                    summary="unknown tool",
                    error=f"no such tool: {name}",
                )
            )
            return None
        result, record = tool(**kwargs)
        self.calls.append(record)
        return result

    def describe(self) -> list[dict]:
        """Tool catalogue, for the API."""
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools().values()
        ]
