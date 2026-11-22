"""Live status for every external data source, derived rather than declared.

The Data Sources page used to list only the three Indian water providers,
because they were the only ones with a ``data_sources`` row. Six more
services now feed the platform, and a page that calls itself "where the
platform's numbers come from" while omitting most of them is not doing its
job.

**Nothing here is configured.** Each card's status comes from what that
source last actually produced: rows in a table, files in a cache, a
timestamp on a cached response. A provider that has never been fetched says
so; one whose data has aged past its own cadence says that instead.

Four states, and the distinction between the last two matters:

``live``          reachable, and its newest data is within cadence.
``stale``         its data has aged out. Nothing is broken; it is just old.
``sync_paused``   it answered and refused. Not an outage.
``unavailable``   it could not be reached, or was never configured.

Raw errors are carried separately from the one-line summary. An error string
on a card reads as breakage even when the situation is a server politely
declining.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _cache_root() -> Path:
    """Where the fetch jobs write, resolved the same way they resolve it."""
    configured = Path(settings.water_cache_dir)
    return configured if configured.is_absolute() else REPO_ROOT / configured


@dataclass(slots=True)
class ProviderCard:
    """One external source, as the page shows it."""

    key: str
    name: str
    organisation: str
    what_it_feeds: str
    expected_cadence: str
    attribution: str
    state: str
    detail: str
    records_held: int
    last_sync: datetime | None = None
    technical_detail: str | None = None
    evidence_level: str | None = None
    url: str | None = None

    @property
    def tone(self) -> str:
        """Colour for the badge. Amber for paused and stale, red only for down."""
        return {"live": "ok", "stale": "warn", "sync_paused": "warn"}.get(
            self.state, "bad"
        )

    @property
    def label(self) -> str:
        """Human-readable status."""
        return {
            "live": "Live",
            "stale": "Stale",
            "sync_paused": "Sync paused",
            "unavailable": "Unavailable",
        }[self.state]

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the API."""
        return {
            "key": self.key,
            "name": self.name,
            "organisation": self.organisation,
            "what_it_feeds": self.what_it_feeds,
            "expected_cadence": self.expected_cadence,
            "attribution": self.attribution,
            "url": self.url,
            "evidence_level": self.evidence_level,
            "status": {
                "state": self.state,
                "label": self.label,
                "tone": self.tone,
                "detail": self.detail,
                "records_held": self.records_held,
                "technical_detail": self.technical_detail,
            },
            "last_success_at": self.last_sync.isoformat() if self.last_sync else None,
        }


def _age_state(
    last: datetime | None, cadence_days: float, now: datetime
) -> tuple[str, str]:
    """Live or stale, from how long ago the source last produced something."""
    if last is None:
        return "unavailable", "Never fetched in this deployment."
    age = (now - last).days
    if age > cadence_days * 3:
        return (
            "stale",
            f"Last fetched {age} days ago, past this source's expected cadence.",
        )
    return "live", f"Last fetched {_when(last, now)}."


def _when(moment: datetime, now: datetime) -> str:
    """A short, honest description of how long ago something happened."""
    delta = now - moment
    if delta < timedelta(hours=1):
        return "within the hour"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} hours ago"
    return f"{delta.days} days ago"


def _newest_file(directory: Path, pattern: str = "*.json") -> datetime | None:
    """Modification time of the newest cached response, or ``None``."""
    if not directory.exists():
        return None
    files = list(directory.glob(pattern))
    if not files:
        return None
    return datetime.fromtimestamp(
        max(f.stat().st_mtime for f in files), tz=UTC
    )


def sentinel2_card(db: Session, now: datetime) -> ProviderCard:
    """Sentinel-2 L2A, which feeds every optical index and detection."""
    from app.models.optical import OpticalIndexObservation

    count = db.scalar(select(func.count(OpticalIndexObservation.id))) or 0
    newest = db.scalar(select(func.max(OpticalIndexObservation.observed_on)))
    last = (
        datetime.combine(newest, datetime.min.time(), tzinfo=UTC) if newest else None
    )
    # Sentinel-2 revisits every five days, and cloud removes more, so a
    # fortnight without a clear scene is normal rather than a fault.
    state, detail = _age_state(last, 14, now)
    if count == 0:
        state, detail = "unavailable", "No readings stored. Run the fetch job."
    return ProviderCard(
        key="sentinel2",
        name="Copernicus Sentinel-2 L2A",
        organisation="European Space Agency / Copernicus",
        what_it_feeds=(
            "NDCI, NDTI and FDI per region, and every optical detection "
            "raised from them."
        ),
        expected_cadence="~5 days per region, cloud permitting",
        attribution=f"Contains modified Copernicus Sentinel data {now.year}",
        url="https://dataspace.copernicus.eu",
        evidence_level="OBSERVED",
        state=state,
        detail=detail,
        records_held=count,
        last_sync=last,
    )


def sentinel1_card(db: Session, now: datetime) -> ProviderCard:
    """Sentinel-1 GRD, used for SAR screening and the incident replay."""
    from app.models.ml import PredictionLog

    count = (
        db.scalar(
            select(func.count(PredictionLog.id)).where(
                PredictionLog.endpoint.like("%screen_sentinel1%")
            )
        )
        or 0
    )
    last = db.scalar(
        select(func.max(PredictionLog.created_at)).where(
            PredictionLog.endpoint.like("%screen_sentinel1%")
        )
    )
    state, detail = _age_state(last, 14, now)
    if count == 0:
        state = "unavailable"
        detail = "No tiles screened in this deployment."
    else:
        detail += (
            " Screening only: no oil detection has been confirmed, and the "
            "model is still outside the distribution its accuracy was "
            "measured on."
        )
    return ProviderCard(
        key="sentinel1",
        name="Copernicus Sentinel-1 GRD",
        organisation="European Space Agency / Copernicus",
        what_it_feeds=(
            "SAR tiles screened by the oil-slick classifier, and the "
            "historical incident replay."
        ),
        expected_cadence="~6 days per region",
        attribution=f"Contains modified Copernicus Sentinel data {now.year}",
        url="https://dataspace.copernicus.eu",
        evidence_level="DETECTED",
        state=state,
        detail=detail,
        records_held=count,
        last_sync=last,
    )


def cmems_card(now: datetime) -> ProviderCard:
    """Copernicus Marine: surface currents and ocean-colour chlorophyll."""
    directory = _cache_root() / "cmems"
    last = _newest_file(directory)
    count = len(list(directory.glob("*.json"))) if directory.exists() else 0
    state, detail = _age_state(last, 7, now)
    if count == 0:
        state, detail = "unavailable", "No cached products. Run the fetch job."
    return ProviderCard(
        key="cmems",
        name="Copernicus Marine Service",
        organisation="Mercator Ocean International",
        what_it_feeds=(
            "Surface currents driving the drift simulator, and chlorophyll-a "
            "as an independent cross-check on this platform's own NDCI."
        ),
        expected_cadence="daily",
        attribution="Generated using E.U. Copernicus Marine Service Information",
        url="https://marine.copernicus.eu",
        evidence_level="INFERRED (currents) / OBSERVED (chlorophyll)",
        state=state,
        detail=detail,
        records_held=count,
        last_sync=last,
    )


def open_meteo_card(now: datetime) -> ProviderCard:
    """Open-Meteo wind, wave and sea-surface temperature."""
    from app.vision.marine_conditions import ATTRIBUTION, MarineConditionsClient

    cached = MarineConditionsClient.load() or {}
    items = cached.get("items", [])
    last = None
    if cached.get("fetched_at"):
        try:
            last = datetime.fromisoformat(cached["fetched_at"])
        except ValueError:
            last = None
    # Hourly data: a day old is already past useful, two days is stale.
    state, detail = _age_state(last, 1, now)
    if not items:
        state, detail = "unavailable", "No conditions cached. Run the fetch job."
    return ProviderCard(
        key="open_meteo",
        name="Open-Meteo",
        organisation="Open-Meteo.com",
        what_it_feeds=(
            "Wind, wave height and sea-surface temperature per region, and "
            "the low-wind flag that marks SAR evidence as ambiguous."
        ),
        expected_cadence="hourly",
        attribution=ATTRIBUTION,
        url="https://open-meteo.com",
        evidence_level="INFERRED",
        state=state,
        detail=detail,
        records_held=len(items),
        last_sync=last,
        technical_detail=cached.get("error"),
    )


def gfw_card(now: datetime) -> ProviderCard:
    """Global Fishing Watch aggregate vessel activity."""
    from app.vision.gfw_client import ATTRIBUTION, ATTRIBUTION_URL

    directory = _cache_root() / "gfw"
    last = _newest_file(directory)
    count = len(list(directory.glob("*.json"))) if directory.exists() else 0
    # The effort product lags about a week while AIS is processed, so a
    # fortnight old is still normal.
    state, detail = _age_state(last, 14, now)
    if count == 0:
        state, detail = "unavailable", "No cached activity. Run the fetch job."
    else:
        detail += " Aggregate only: no vessel identity is stored or shown."
    return ProviderCard(
        key="gfw",
        name="Global Fishing Watch",
        organisation="Global Fishing Watch",
        what_it_feeds=(
            "Aggregate AIS-derived vessel activity per region, by flag state."
        ),
        expected_cadence="weekly, lagging ~7 days behind real time",
        attribution=ATTRIBUTION,
        url=ATTRIBUTION_URL,
        evidence_level="INFERRED",
        state=state,
        detail=detail,
        records_held=count,
        last_sync=last,
    )


def gemini_card(db: Session, now: datetime) -> ProviderCard:
    """The optional narrative layer."""
    from app.models.intelligence import Report

    count = (
        db.scalar(
            select(func.count(Report.id)).where(Report.ai_narrative.isnot(None))
        )
        or 0
    )
    last = db.scalar(select(func.max(Report.ai_generated_at)))
    model = db.scalar(
        select(Report.ai_model).where(Report.ai_model.isnot(None)).limit(1)
    )

    if not settings.gemini_api_key:
        state = "unavailable"
        detail = "No API key configured. Reports render from computed values."
    elif count == 0:
        state = "sync_paused"
        detail = (
            "Configured, but no narrative has been generated. Reports render "
            "from computed values, which is the normal fallback."
        )
    else:
        state = "live"
        detail = (
            f"{count} report narrative(s) generated by {model} and cached. "
            "Opening a report calls no model."
        )
    return ProviderCard(
        key="gemini",
        name=f"Google Gemini ({model or settings.gemini_model})",
        organisation="Google",
        what_it_feeds=(
            "Optional prose summaries of reports. Every figure in a summary "
            "is checked against the report's computed values before it is "
            "stored; one that fails is discarded, not flagged."
        ),
        expected_cadence="on demand, cached indefinitely",
        attribution="Summaries generated by Google Gemini",
        url="https://ai.google.dev",
        evidence_level="Not evidence: prose over computed values",
        state=state,
        detail=detail,
        records_held=count,
        last_sync=last,
    )


def external_providers(db: Session, now: datetime | None = None) -> list[dict]:
    """Every external source this platform reads, with its real state."""
    moment = now or datetime.now(UTC)
    cards = [
        sentinel2_card(db, moment),
        sentinel1_card(db, moment),
        cmems_card(moment),
        open_meteo_card(moment),
        gfw_card(moment),
        gemini_card(db, moment),
    ]
    return [card.to_dict() for card in cards]
