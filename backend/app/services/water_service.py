"""Query and assembly layer for water intelligence.

Routes parse and delegate; this module holds the logic. Three things here are
worth knowing about before reading the code.

**Status is computed, not trusted.** ``water_bodies.cached_status`` exists so
the map can colour thousands of features in one query, but every detail
response recomputes the status from observations. A cache that silently goes
stale would be a source of exactly the kind of confident-but-wrong claim this
platform is built to avoid, so the cache is only ever an optimisation for
bulk views, never the answer to "what is the status of this river?".

**Spatial queries are real.** Bounding-box filtering happens in SQL against
indexed latitude/longitude columns. Radius search pre-filters with a bounding
box in SQL and then applies an exact haversine distance in Python, so the
result is a true circle rather than the square that a naive implementation
returns.

**Missing is not zero.** Every aggregate distinguishes "no station reported
this" from "the value is zero". Counts of water bodies without recent data
are first-class outputs, not omissions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.models.enums import WaterStatus
from app.models.water import (
    DataSource,
    District,
    IngestionRun,
    MonitoringStation,
    State,
    WaterBody,
    WaterQualityObservation,
)
from app.models.water_geo import SourceClassification
from app.services.provider_status import external_providers
from app.water.freshness import CADENCE_DAYS, MIN_NO_RECENT_DAYS, Cadence
from app.water.matching import PLACE_ALIASES, haversine_km, normalise_name
from app.water.parameters import BY_KEY
from app.water.standards import ReferenceSelection, compare, select_reference
from app.water.status import (
    ClassificationRef,
    Measurement,
    StatusResult,
    evaluate,
    status_rank,
)

# Cap on features returned by one map query. The map asks for a viewport, not
# the whole country; without a cap a zoomed-out request would try to serialise
# every station in India into one response.
MAP_FEATURE_LIMIT = 2000
SEARCH_LIMIT = 25


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise a database datetime to aware UTC (SQLite stores naive)."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _cadence_for(db: Session, source_key: str = "cpcb_nwdp") -> Cadence:
    """The declared cadence of a source, for freshness judgement."""
    source = db.scalar(select(DataSource).where(DataSource.key == source_key))
    if source is None:
        return Cadence.UNKNOWN
    try:
        return Cadence(source.expected_cadence)
    except ValueError:
        return Cadence.UNKNOWN


def _cadence_for_measurements(db: Session, measurements: list[Measurement]) -> Cadence:
    """The cadence of whichever source produced the newest measurement.

    A water body can hold hourly sensor readings and decade-old laboratory
    samples at once. Judging the newest reading against another source's
    cadence produced sentences like "within the source's monthly reporting
    cadence" about a value taken twenty minutes ago.
    """
    if not measurements:
        return _cadence_for(db)
    newest = max(measurements, key=lambda m: m.observed_at)
    if not newest.source:
        return _cadence_for(db)
    source = db.scalar(
        select(DataSource).where(
            or_(DataSource.name == newest.source, DataSource.key == newest.source)
        )
    )
    if source is None:
        return _cadence_for(db)
    try:
        return Cadence(source.expected_cadence)
    except ValueError:
        return Cadence.UNKNOWN


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def _only_latest_per_parameter(scope: ColumnElement, value: int) -> ColumnElement[bool]:
    """Keep only each parameter's most recent observation within ``scope``.

    ``scope`` is the column that bounds the question --
    ``WaterQualityObservation.water_body_id`` for a water body,
    ``station_id`` for one station. Ties (two stations, or two agencies,
    reporting the same parameter at the same instant) survive this filter and
    are resolved by the caller, which keeps the first row it sees.
    """
    newest = (
        select(
            WaterQualityObservation.parameter,
            func.max(WaterQualityObservation.observed_at),
        )
        .where(scope == value)
        .group_by(WaterQualityObservation.parameter)
    )
    return tuple_(
        WaterQualityObservation.parameter,
        WaterQualityObservation.observed_at,
    ).in_(newest)


def compute_status(
    db: Session,
    body: WaterBody,
    *,
    reference: str | None = None,
    as_of_observation: bool = False,
    measurements: list[Measurement] | None = None,
) -> StatusResult:
    """Compute a water body's status from its most recent observations.

    Reads only the latest observation per parameter. Regulatory limits are
    written against individual samples, so averaging months together would
    both smear real spikes and compare against the wrong thing.

    Args:
        db: open session.
        body: the water body to classify.
        reference: a standard code or designated-use class chosen by the
            reader. Without one the reference is *selected* -- see
            ``standards.select_reference`` -- and may be none at all.
        as_of_observation: evaluate as at the date of the latest observation
            rather than today. This is what makes the platform useful on data
            that is years old without becoming dishonest. The present-tense
            answer for Mithi River is ``NO_RECENT_DATA``, because a 2021
            sample cannot describe the river today; but "as of 02 Dec 2021,
            BOD was above the class C limit" is a true, checkable statement,
            and discarding it would throw away the actual finding. The two
            are returned as separate fields and the historical one is always
            rendered with its date attached.
        measurements: already-read latest measurements, to avoid reading them
            twice when both the present-tense and the as-measured verdict are
            wanted for the same water body. They are the same rows either
            way; only the interpretation differs.
    """
    if measurements is None:
        measurements = latest_measurements(db, body)
    selection = reference_for(body, reference)
    return _classify(db, body, measurements, selection, as_of_observation)


def latest_measurements(db: Session, body: WaterBody) -> list[Measurement]:
    """The most recent measurement of every parameter on this water body.

    Served from the cached summary when it is current. On the Ganga the query
    below reads 347k observations and costs 630 ms; the cache holds the forty
    rows it distils to.
    """
    if summary_is_current(body) and (body.summary or {}).get("measurements") is not None:
        return [
            Measurement(
                parameter_key=entry["parameter"],
                value=entry["value"],
                observed_at=datetime.fromisoformat(entry["observed_at"]),
                unit=entry.get("unit"),
                source=entry.get("source"),
            )
            for entry in body.summary["measurements"]
            if entry.get("observed_at")
        ]

    rows = db.execute(
        select(
            WaterQualityObservation.parameter,
            WaterQualityObservation.normalized_value,
            WaterQualityObservation.value,
            WaterQualityObservation.observed_at,
            WaterQualityObservation.normalized_unit,
            DataSource.key,
            DataSource.name,
        )
        .join(DataSource, DataSource.id == WaterQualityObservation.source_id)
        .where(WaterQualityObservation.water_body_id == body.id)
        .where(_only_latest_per_parameter(WaterQualityObservation.water_body_id, body.id))
        .order_by(WaterQualityObservation.observed_at.desc())
    ).all()

    latest: dict[str, Measurement] = {}
    for parameter, normalized, raw, observed_at, unit, source_key, source_name in rows:
        observed_at = _as_utc(observed_at)
        if observed_at is None or parameter in latest:
            continue
        # Newest first, so the first row for a parameter is the newest
        # measurement of it -- whichever agency made it. Both sources are
        # kept in the database; the status uses the most recent value and
        # says which source it came from.
        value = normalized if normalized is not None else raw
        latest[parameter] = Measurement(
            parameter_key=parameter,
            value=value,
            observed_at=observed_at,
            unit=unit,
            source=source_name or source_key,
        )

    return list(latest.values())


def _classify(
    db: Session,
    body: WaterBody,
    measurements: list[Measurement],
    selection: ReferenceSelection,
    as_of_observation: bool,
) -> StatusResult:
    """Turn measurements into a status against the chosen reference."""
    classifications = classifications_for(db, body)

    if as_of_observation and measurements:
        # Stand the clock at the moment of sampling. The freshness gate then
        # passes and the parameter comparisons run, producing the verdict
        # that was true on that date. The caller labels it with the date.
        newest = max(m.observed_at for m in measurements)
        result = evaluate(
            measurements,
            reference=selection,
            classifications=classifications,
            cadence=_cadence_for_measurements(db, measurements),
            now=newest,
        )
        # With the clock stopped at the sample date the freshness sentence
        # would read "0 days ago": true of that frozen clock, false for the
        # reader. Replace it with a statement of what was actually done.
        stale_line = result.freshness.summary()
        result.reasons = [
            (
                f"Assessed as at the observation date, {newest:%d %b %Y}. "
                "This describes that sample, not the water body today."
            )
            if reason == stale_line
            else reason
            for reason in result.reasons
        ]
        return result

    return evaluate(
        measurements,
        reference=selection,
        classifications=classifications,
        cadence=_cadence_for_measurements(db, measurements),
    )


def reference_for(body: WaterBody, explicit: str | None = None) -> ReferenceSelection:
    """The reference standard that applies to ``body`` (or why none does)."""
    return select_reference(
        body.water_type, explicit=explicit, designated_use=body.designated_use
    )


def classifications_for(db: Session, body: WaterBody) -> list[ClassificationRef]:
    """Official classifications published for this water body, if any."""
    return [
        ClassificationRef(
            source=c.source,
            classification_type=c.classification_type,
            assessment_year=c.assessment_year,
            priority=c.priority,
            stretch_name=c.stretch_name,
            source_reference=c.source_reference,
        )
        for c in db.scalars(
            select(SourceClassification).where(
                SourceClassification.water_body_id == body.id
            )
        )
    ]


def summary_is_current(body: WaterBody) -> bool:
    """Whether this body's cached summary still describes its observations.

    The observation count is the test: it changes whenever an ingest adds a
    row, and it is already maintained. A summary built from a different count
    predates that ingest.
    """
    return (
        body.summary is not None
        and body.summary_observation_count == body.observation_count
    )


def build_summary(db: Session, body: WaterBody) -> dict:
    """Compute everything the detail page and the RAG read repeatedly.

    One pass over the water body's observations, producing what four separate
    aggregates used to produce per request: the latest measurement of every
    parameter, the per-source counts and recency, and the observation span.
    """
    per_source = [
        {
            "key": row.key,
            "name": row.name,
            "organisation": row.organisation,
            "source_type": row.source_type,
            "observation_method": row.observation_method,
            "expected_cadence": row.expected_cadence,
            "reliability_note": row.reliability_note,
            "url": row.url,
            "dataset": row.dataset,
            "licence": row.licence,
            "observation_count": int(row.observations or 0),
            "parameter_count": int(row.parameters or 0),
            "first_observed_at": _iso(row.first_observed),
            "latest_observed_at": _iso(row.latest_observed),
            "retrieved_at": _iso(row.retrieved),
        }
        for row in db.execute(
            select(
                DataSource.key,
                DataSource.name,
                DataSource.organisation,
                DataSource.source_type,
                DataSource.observation_method,
                DataSource.expected_cadence,
                DataSource.reliability_note,
                DataSource.url,
                DataSource.dataset,
                DataSource.licence,
                func.count(WaterQualityObservation.id).label("observations"),
                func.count(func.distinct(WaterQualityObservation.parameter)).label(
                    "parameters"
                ),
                func.min(WaterQualityObservation.observed_at).label("first_observed"),
                func.max(WaterQualityObservation.observed_at).label("latest_observed"),
                func.max(WaterQualityObservation.retrieved_at).label("retrieved"),
            )
            .join(DataSource, DataSource.id == WaterQualityObservation.source_id)
            .where(WaterQualityObservation.water_body_id == body.id)
            .group_by(DataSource.id)
        ).all()
    ]
    per_source.sort(key=lambda entry: entry["latest_observed_at"] or "", reverse=True)

    measurements = [
        {
            "parameter": m.parameter_key,
            "value": m.value,
            "unit": m.unit,
            "observed_at": _iso(m.observed_at),
            "source": m.source,
        }
        for m in latest_measurements(db, body)
    ]

    span = db.execute(
        select(
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
        ).where(WaterQualityObservation.water_body_id == body.id)
    ).one()

    return {
        "version": 1,
        "sources": per_source,
        "measurements": measurements,
        "first_observed_at": _iso(span[0]),
        "latest_observed_at": _iso(span[1]),
        "parameter_count": len(measurements),
    }


def _month_key(db: Session, column: ColumnElement) -> ColumnElement:
    """A month bucket for counting distinct sampling months, per dialect."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return func.date_trunc("month", column)
    return func.strftime("%Y-%m", column)


def build_all_summaries(db: Session) -> dict[int, dict]:
    """Every water body's summary, in two set-based queries.

    Building these one body at a time turned a 25-second job into a
    twenty-minute one. Grouping by ``water_body_id`` instead does the whole
    country in about seven seconds.
    """
    sources = {
        row.id: row
        for row in db.execute(
            select(
                DataSource.id,
                DataSource.key,
                DataSource.name,
                DataSource.organisation,
                DataSource.source_type,
                DataSource.observation_method,
                DataSource.expected_cadence,
                DataSource.reliability_note,
                DataSource.url,
                DataSource.dataset,
                DataSource.licence,
            )
        ).all()
    }

    per_body: dict[int, dict] = {}

    for row in db.execute(
        select(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.source_id,
            func.count(WaterQualityObservation.id),
            func.count(func.distinct(WaterQualityObservation.parameter)),
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.retrieved_at),
        )
        .where(WaterQualityObservation.water_body_id.is_not(None))
        .group_by(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.source_id,
        )
    ).all():
        body_id, source_id, count, parameters, first, last, retrieved = row
        source = sources.get(source_id)
        if source is None:
            continue
        entry = per_body.setdefault(
            body_id, {"version": 1, "sources": [], "measurements": []}
        )
        entry["sources"].append(
            {
                "key": source.key,
                "name": source.name,
                "organisation": source.organisation,
                "source_type": source.source_type,
                "observation_method": source.observation_method,
                "expected_cadence": source.expected_cadence,
                "reliability_note": source.reliability_note,
                "url": source.url,
                "dataset": source.dataset,
                "licence": source.licence,
                "observation_count": int(count or 0),
                "parameter_count": int(parameters or 0),
                "first_observed_at": _iso(first),
                "latest_observed_at": _iso(last),
                "retrieved_at": _iso(retrieved),
            }
        )

    # The latest measurement of every parameter, for every body, in one pass.
    newest = (
        select(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.parameter,
            func.max(WaterQualityObservation.observed_at).label("observed_at"),
        )
        .where(WaterQualityObservation.water_body_id.is_not(None))
        .group_by(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.parameter,
        )
    )
    for row in db.execute(
        select(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.parameter,
            WaterQualityObservation.normalized_value,
            WaterQualityObservation.value,
            WaterQualityObservation.normalized_unit,
            WaterQualityObservation.observed_at,
            DataSource.name,
        )
        .join(DataSource, DataSource.id == WaterQualityObservation.source_id)
        .where(
            tuple_(
                WaterQualityObservation.water_body_id,
                WaterQualityObservation.parameter,
                WaterQualityObservation.observed_at,
            ).in_(newest)
        )
    ).all():
        body_id, parameter, normalized, value, unit, observed_at, source_name = row
        entry = per_body.setdefault(
            body_id, {"version": 1, "sources": [], "measurements": []}
        )
        # Ties (two stations at the same instant) keep the first seen, which
        # is what the per-request path does too.
        if any(m["parameter"] == parameter for m in entry["measurements"]):
            continue
        entry["measurements"].append(
            {
                "parameter": parameter,
                "value": normalized if normalized is not None else value,
                "unit": unit,
                "observed_at": _iso(observed_at),
                "source": source_name,
            }
        )

    # Per-parameter counts and spans: what the trend selector offers and
    # what the data-quality panel counts.
    for row in db.execute(
        select(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.parameter,
            func.count(WaterQualityObservation.id),
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
        )
        .where(WaterQualityObservation.water_body_id.is_not(None))
        .group_by(
            WaterQualityObservation.water_body_id,
            WaterQualityObservation.parameter,
        )
    ).all():
        body_id, parameter, count, first, last = row
        entry = per_body.setdefault(
            body_id, {"version": 1, "sources": [], "measurements": []}
        )
        entry.setdefault("parameters", []).append(
            {
                "parameter": parameter,
                "point_count": int(count or 0),
                "first_observed_at": _iso(first),
                "last_observed_at": _iso(last),
            }
        )

    # Distinct months sampled, which the data-quality panel reports.
    for row in db.execute(
        select(
            WaterQualityObservation.water_body_id,
            func.count(
                func.distinct(_month_key(db, WaterQualityObservation.observed_at))
            ),
        )
        .where(WaterQualityObservation.water_body_id.is_not(None))
        .group_by(WaterQualityObservation.water_body_id)
    ).all():
        body_id, months = row
        entry = per_body.setdefault(
            body_id, {"version": 1, "sources": [], "measurements": []}
        )
        entry["sampling_months"] = int(months or 0)

    for entry in per_body.values():
        entry.setdefault("parameters", [])
        entry.setdefault("sampling_months", 0)
        entry["sources"].sort(
            key=lambda item: item["latest_observed_at"] or "", reverse=True
        )
        firsts = [
            s["first_observed_at"] for s in entry["sources"] if s["first_observed_at"]
        ]
        lasts = [
            s["latest_observed_at"] for s in entry["sources"] if s["latest_observed_at"]
        ]
        entry["first_observed_at"] = min(firsts) if firsts else None
        entry["latest_observed_at"] = max(lasts) if lasts else None
        entry["parameter_count"] = len(entry["measurements"])

    return per_body


def store_summary(db: Session, body: WaterBody) -> dict:
    """Build the summary and record what it was built from."""
    summary = build_summary(db, body)
    body.summary = summary
    body.summary_observation_count = body.observation_count
    body.summary_computed_at = datetime.now(UTC)
    return summary


def summary_for(db: Session, body: WaterBody) -> dict:
    """The cached summary, or a freshly computed one.

    Never returns a stale answer: a summary built before the latest ingest is
    recomputed here rather than served. The recomputation is not stored,
    because a request is not the place to write; the job will store it.
    """
    if summary_is_current(body):
        return body.summary
    return build_summary(db, body)


def refresh_cached_statuses(db: Session, *, limit: int | None = None) -> int:
    """Recompute and store ``cached_status`` for map and list views.

    Run after ingestion. Returns the number of water bodies updated.
    """
    stmt = select(WaterBody).order_by(WaterBody.id)
    if limit is not None:
        stmt = stmt.limit(limit)

    # Every body's summary up front, in two queries rather than three per
    # body. This is what the detail page and the RAG read instead of
    # aggregating a river's whole history per request.
    summaries = build_all_summaries(db)
    now = datetime.now(UTC)

    updated = 0
    for body in db.scalars(stmt):
        body.summary = summaries.get(
            body.id, {"version": 1, "sources": [], "measurements": []}
        )
        body.summary_observation_count = body.observation_count
        body.summary_computed_at = now
        measured = latest_measurements(db, body)
        result = compute_status(db, body, measurements=measured)
        body.cached_status = str(result.status)
        # Colouring every feature NO_RECENT_DATA would make the map true but
        # useless. The historical band is cached alongside so the map can show
        # what the last measurement found, labelled with its date.
        historical = compute_status(
            db, body, as_of_observation=True, measurements=measured
        )
        body.cached_historical_status = str(historical.status)
        updated += 1
    db.commit()
    return updated


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class WaterBodyFilters:
    """Filters accepted by the list and map endpoints."""

    state: str | None = None
    district: str | None = None
    water_type: str | None = None
    status: str | None = None
    has_recent_data: bool | None = None
    query: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    """(min_lat, min_lon, max_lat, max_lon)."""


def bodies_in_state(state: str) -> Select:
    """IDs of water bodies with at least one station in ``state``."""
    return (
        select(MonitoringStation.water_body_id)
        .join(State, State.id == MonitoringStation.state_id)
        .where(
            MonitoringStation.water_body_id.is_not(None),
            or_(
                func.lower(State.slug) == state.lower(),
                func.upper(State.code) == state.upper(),
            ),
        )
        .distinct()
    )


def bodies_in_district(district: str) -> Select:
    """IDs of water bodies with at least one station in ``district``."""
    return (
        select(MonitoringStation.water_body_id)
        .join(District, District.id == MonitoringStation.district_id)
        .where(
            MonitoringStation.water_body_id.is_not(None),
            func.lower(District.slug) == district.lower(),
        )
        .distinct()
    )


def _apply_filters(stmt: Select, filters: WaterBodyFilters) -> Select:
    """Translate filters into SQL predicates."""
    # Geography filters match on where a water body's *stations* are, not on
    # the single state recorded on the body. A river is keyed nationally and
    # records the state of whichever station created it; filtering on that
    # alone made the Yamuna vanish from Delhi because it was first seen in
    # Uttar Pradesh.
    if filters.state:
        stmt = stmt.where(WaterBody.id.in_(bodies_in_state(filters.state)))
    if filters.district:
        stmt = stmt.where(WaterBody.id.in_(bodies_in_district(filters.district)))
    if filters.water_type:
        stmt = stmt.where(WaterBody.water_type == filters.water_type)
    if filters.status:
        stmt = stmt.where(WaterBody.cached_status == filters.status)
    if filters.query:
        needle = f"%{filters.query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(WaterBody.name).like(needle),
                func.lower(WaterBody.normalized_name).like(needle),
            )
        )
    if filters.bbox:
        min_lat, min_lon, max_lat, max_lon = filters.bbox
        stmt = stmt.where(
            WaterBody.centroid_lat.is_not(None),
            WaterBody.centroid_lon.is_not(None),
            WaterBody.centroid_lat >= min_lat,
            WaterBody.centroid_lat <= max_lat,
            WaterBody.centroid_lon >= min_lon,
            WaterBody.centroid_lon <= max_lon,
        )
    if filters.has_recent_data is True:
        stmt = stmt.where(WaterBody.latest_observed_at.is_not(None))
    elif filters.has_recent_data is False:
        stmt = stmt.where(WaterBody.latest_observed_at.is_(None))
    return stmt


def list_water_bodies(
    db: Session,
    filters: WaterBodyFilters,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """A page of water bodies plus the total matching count."""
    base = select(WaterBody)
    filtered = _apply_filters(base, filters)

    total = db.scalar(select(func.count()).select_from(filtered.subquery())) or 0

    rows = db.scalars(
        filtered.order_by(WaterBody.observation_count.desc(), WaterBody.name)
        .limit(limit)
        .offset(offset)
    ).all()

    return summarise_bodies(db, list(rows)), total


class Lookups:
    """Strongly held state, district and water-body rows for bulk summaries.

    ``summarise_*`` used ``db.get`` per row. The session's identity map holds
    *weak* references, so objects loaded in advance are garbage-collected
    before they are needed and every ``get`` becomes a SELECT again -- 2,356
    of them for the national station map (2.2 s). Holding the rows here keeps
    that to at most three ``IN`` queries.
    """

    def __init__(self) -> None:
        """Start empty; ``preload`` fills the maps."""
        self.states: dict[int, State] = {}
        self.districts: dict[int, District] = {}
        self.bodies: dict[int, WaterBody] = {}

    def state(self, db: Session, key: int | None) -> State | None:
        """Held row, falling back to a lookup."""
        if not key:
            return None
        return self.states.get(key) or db.get(State, key)

    def district(self, db: Session, key: int | None) -> District | None:
        """Held row, falling back to a lookup."""
        if not key:
            return None
        return self.districts.get(key) or db.get(District, key)

    def body(self, db: Session, key: int | None) -> WaterBody | None:
        """Held row, falling back to a lookup."""
        if not key:
            return None
        return self.bodies.get(key) or db.get(WaterBody, key)


def _load(db: Session, model: Any, ids: set[int]) -> dict[int, Any]:
    out: dict[int, Any] = {}
    id_list = list(ids)
    for start in range(0, len(id_list), 900):  # stay under SQLite's variable cap
        chunk = id_list[start : start + 900]
        out.update(
            {row.id: row for row in db.scalars(select(model).where(model.id.in_(chunk)))}
        )
    return out


def preload(
    db: Session,
    *,
    bodies: list[WaterBody] | None = None,
    stations: list[MonitoringStation] | None = None,
) -> Lookups:
    """Fetch every related state, district and water body up front."""
    bodies = bodies or []
    stations = stations or []
    lookups = Lookups()
    lookups.states = _load(db, State, {b.state_id for b in bodies if b.state_id})
    lookups.districts = _load(
        db,
        District,
        {b.district_id for b in bodies if b.district_id}
        | {s.district_id for s in stations if s.district_id},
    )
    lookups.bodies = _load(
        db, WaterBody, {s.water_body_id for s in stations if s.water_body_id}
    )
    return lookups


def summarise_bodies(db: Session, bodies: list[WaterBody], **kwargs: Any) -> list[dict]:
    """Summarise many water bodies without a query per row."""
    lookups = preload(db, bodies=bodies)
    return [summarise_body(db, b, lookups=lookups, **kwargs) for b in bodies]


def summarise_stations(db: Session, stations: list[MonitoringStation]) -> list[dict]:
    """Summarise many stations without a query per row."""
    lookups = preload(db, stations=stations)
    return [summarise_station(db, s, lookups=lookups) for s in stations]


def summarise_body(
    db: Session,
    body: WaterBody,
    *,
    include_state: bool = True,
    lookups: Lookups | None = None,
) -> dict:
    """Compact representation for lists, maps and search results."""
    lookups = lookups or Lookups()
    state = lookups.state(db, body.state_id)
    district = lookups.district(db, body.district_id)
    return {
        "id": body.id,
        "slug": body.slug,
        "name": body.name,
        "water_type": str(body.water_type),
        "state": state.name if state and include_state else None,
        "state_slug": state.slug if state and include_state else None,
        "district": district.name if district else None,
        "district_slug": district.slug if district else None,
        "latitude": body.centroid_lat,
        "longitude": body.centroid_lon,
        "station_count": body.station_count,
        "observation_count": body.observation_count,
        "latest_observed_at": (
            _as_utc(body.latest_observed_at).isoformat()
            if body.latest_observed_at
            else None
        ),
        "status": body.cached_status,
        "latest_available_status": body.cached_historical_status,
        "match_confidence": body.match_confidence,
        "match_method": body.match_method,
    }


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def get_water_body_detail(
    db: Session, slug: str, *, reference: str | None = None
) -> dict | None:
    """Everything the water-body page needs, with provenance throughout."""
    body = db.scalar(select(WaterBody).where(WaterBody.slug == slug))
    if body is None:
        return None

    # Read each parameter's latest measurement once: the two verdicts below
    # differ only in how they read the same rows.
    measured = latest_measurements(db, body)
    status = compute_status(db, body, reference=reference, measurements=measured)
    source_records = sources_for_body(db, body)
    # The present-tense verdict may be NO_RECENT_DATA while the measurements
    # themselves show a clear exceedance. Both are reported: one answers
    # "what is it like now?" (honestly, "we do not know"), the other answers
    # "what did the last measurement show?" -- always carrying its date.
    historical = compute_status(
        db, body, reference=reference, as_of_observation=True, measurements=measured
    )
    stations = db.scalars(
        select(MonitoringStation)
        .where(MonitoringStation.water_body_id == body.id)
        .order_by(MonitoringStation.latest_observed_at.desc().nullslast())
    ).all()

    return {
        **summarise_body(db, body),
        "basin": body.basin,
        "sub_basin": body.sub_basin,
        "aliases": body.aliases or [],
        "status_detail": status.to_dict(),
        "latest_available_status": (
            {
                **historical.to_dict(),
                "as_of": (
                    _as_utc(body.latest_observed_at).isoformat()
                    if body.latest_observed_at
                    else None
                ),
                "note": (
                    "Status as at the date of the most recent measurement, "
                    "not a statement about the water body today."
                ),
            }
            if body.latest_observed_at
            else None
        ),
        "parameters": latest_parameters(db, body, reference=reference),
        "reference": reference_for(body, reference).to_dict(),
        "designated_use_recorded": body.designated_use,
        "stations": summarise_stations(db, list(stations)),
        "sources": source_records,
        # What is known about this water body, and what is not: real-time,
        # historical, geometry, satellite, official classification.
        "data_availability": data_availability(db, body),
        **_geography(db, body, status, source_records),
    }


def _geography(
    db: Session,
    body: WaterBody,
    status: StatusResult,
    source_records: list[dict] | None = None,
) -> dict:
    """Phase 2 layers: geometry, data quality, availability, sources panel.

    ``source_records`` is the page's own ``sources_for_body`` result. Passing
    it in avoids aggregating every observation of the water body a second
    time, which on the Ganga's 347k rows cost 384 ms.
    """
    from app.services import geo_service as gs
    from app.water.satellite import images_for

    status_dict = status.to_dict()
    sources = latest_by_source(db, body)
    geometry = gs.water_body_geometry(db, body)
    if source_records is None:
        source_records = sources_for_body(db, body)
    partial = {
        "imagery": images_for(db, body),
        "geometry": geometry,
        "sources": source_records,
        "reference": reference_for(body).to_dict(),
        "latest_available_status": None,
    }
    return {
        "geometry": geometry,
        "geometry_status": body.geometry_status,
        "geometry_status_text": gs.GEOMETRY_STATUS_TEXT.get(body.geometry_status, ""),
        "data_quality": gs.data_quality(db, body, status_dict),
        "availability": gs.availability(body, status_dict, sources),
        "sources_by_recency": sources,
        "sources_panel": gs.sources_panel(db, body, partial),
        "imagery": images_for(db, body),
        "imagery_note": (
            "Satellite scenes are shown as visual evidence. Any index derived "
            "from them is an uncalibrated proxy, never a laboratory measurement."
        ),
    }


def latest_parameters(
    db: Session, body: WaterBody, *, reference: str | None = None
) -> list[dict]:
    """The latest value of every parameter measured on this water body.

    Only parameters that were actually measured appear. A parameter nobody
    sampled is absent rather than rendered as zero or as a reassuring dash,
    and the page says explicitly what was not measured.
    """
    selection = reference_for(body, reference)
    rows = db.execute(
        select(
            WaterQualityObservation.parameter,
            WaterQualityObservation.value,
            WaterQualityObservation.normalized_value,
            WaterQualityObservation.normalized_unit,
            WaterQualityObservation.unit,
            WaterQualityObservation.observed_at,
            WaterQualityObservation.qualitative_value,
            WaterQualityObservation.quality_flag,
            WaterQualityObservation.source_reference,
            MonitoringStation.name,
        )
        .join(
            MonitoringStation,
            MonitoringStation.id == WaterQualityObservation.station_id,
        )
        .where(WaterQualityObservation.water_body_id == body.id)
        .where(_only_latest_per_parameter(WaterQualityObservation.water_body_id, body.id))
        .order_by(WaterQualityObservation.observed_at.desc())
    ).all()

    from app.water.standards import compare

    seen: dict[str, dict] = {}
    for (
        parameter,
        value,
        normalized,
        normalized_unit,
        unit,
        observed_at,
        qualitative,
        flag,
        reference,
        station_name,
    ) in rows:
        if parameter in seen:
            continue
        meta = BY_KEY.get(parameter)
        if meta is None:
            continue

        effective = normalized if normalized is not None else value
        comparison = compare(meta, effective, selection.standard)
        seen[parameter] = {
            "parameter": parameter,
            "label": meta.label,
            "family": str(meta.family),
            "value": effective,
            "raw_value": value,
            "unit": normalized_unit or unit or meta.unit,
            "qualitative_value": qualitative,
            "observed_at": _as_utc(observed_at).isoformat() if observed_at else None,
            "station": station_name,
            "quality_flag": str(flag),
            "source_reference": reference,
            "evidence_type": "MEASURED",
            "comparison": comparison.to_dict(),
            "higher_is_worse": meta.higher_is_worse,
        }

    order = {"biological": 0, "chemical": 1, "physical": 2}
    return sorted(
        seen.values(),
        key=lambda p: (order.get(p["family"], 3), p["label"]),
    )


def summarise_station(
    db: Session, station: MonitoringStation, *, lookups: Lookups | None = None
) -> dict:
    """Compact station record for maps and detail pages."""
    lookups = lookups or Lookups()
    body = lookups.body(db, station.water_body_id)
    district = lookups.district(db, station.district_id)
    return {
        "id": station.id,
        "code": station.station_code,
        "name": station.name,
        "slug": station.slug,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "geo_quality": station.geo_quality,
        "position_descriptor": station.position_descriptor,
        "relationship_type": station.relationship_type,
        "geometry_distance_m": station.geometry_distance_m,
        "agency": station.agency,
        "district": district.name if district else None,
        "water_body": body.name if body else None,
        "water_body_slug": body.slug if body else None,
        "observation_count": station.observation_count,
        "latest_observed_at": (
            _as_utc(station.latest_observed_at).isoformat()
            if station.latest_observed_at
            else None
        ),
    }


def station_detail(db: Session, station_id: int) -> dict | None:
    """One station with its most recent value for every parameter measured.

    The station page answers "what did this specific sampling point find, and
    when?", so values are per-parameter latest rather than a roll-up, and each
    carries the date it was taken.
    """
    station = db.get(MonitoringStation, station_id)
    if station is None:
        return None

    rows = db.execute(
        select(
            WaterQualityObservation.parameter,
            WaterQualityObservation.normalized_value,
            WaterQualityObservation.value,
            WaterQualityObservation.normalized_unit,
            WaterQualityObservation.observed_at,
            WaterQualityObservation.quality_flag,
            WaterQualityObservation.source_reference,
        )
        .where(WaterQualityObservation.station_id == station.id)
        .where(_only_latest_per_parameter(WaterQualityObservation.station_id, station.id))
        .order_by(WaterQualityObservation.observed_at.desc())
    ).all()

    body = db.get(WaterBody, station.water_body_id) if station.water_body_id else None
    selection = reference_for(body) if body is not None else select_reference("other")

    latest: dict[str, dict] = {}
    measurements: list[Measurement] = []
    for parameter, normalized, raw, unit, observed_at, flag, reference in rows:
        observed_at = _as_utc(observed_at)
        if parameter in latest or observed_at is None:
            continue
        meta = BY_KEY.get(parameter)
        if meta is None:
            continue
        value = normalized if normalized is not None else raw
        measurements.append(
            Measurement(parameter_key=parameter, value=value, observed_at=observed_at)
        )
        latest[parameter] = {
            "parameter": parameter,
            "label": meta.label,
            "family": str(meta.family),
            "value": value,
            "unit": unit or meta.unit,
            "observed_at": observed_at.isoformat(),
            "quality_flag": str(flag),
            "source_reference": reference,
            "evidence_type": "MEASURED",
            "comparison": compare(meta, value, selection.standard).to_dict(),
        }

    cadence = _cadence_for_measurements(db, measurements)
    present = evaluate(measurements, reference=selection, cadence=cadence)
    historical = (
        evaluate(
            measurements,
            reference=selection,
            cadence=cadence,
            now=max(m.observed_at for m in measurements),
        )
        if measurements
        else present
    )

    return {
        **summarise_station(db, station),
        "reference": selection.to_dict(),
        "status_detail": present.to_dict(),
        "latest_available_status": (
            {
                **historical.to_dict(),
                "as_of": historical.freshness.observed_at.isoformat(),
            }
            if historical.freshness.observed_at
            else None
        ),
        "parameters": sorted(
            latest.values(),
            key=lambda p: (
                {"biological": 0, "chemical": 1, "physical": 2}.get(p["family"], 3),
                p["label"],
            ),
        ),
    }


def latest_by_source(db: Session, body: WaterBody) -> list[dict]:
    """What each source has for this water body, newest source first.

    This is what makes "the CPCB extract stops in 2021 but CWC sampled it in
    2025" visible instead of being flattened into one date.

    Served from the cached summary when it is current; the aggregate below is
    the fallback, and on the Ganga it costs 240 ms.
    """
    cached = summary_for(db, body)
    if cached.get("sources") is not None:
        return [dict(entry) for entry in cached["sources"]]

    rows = db.execute(
        select(
            DataSource.key,
            DataSource.name,
            DataSource.organisation,
            DataSource.source_type,
            DataSource.observation_method,
            DataSource.expected_cadence,
            DataSource.reliability_note,
            func.count(WaterQualityObservation.id),
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
            func.count(func.distinct(WaterQualityObservation.parameter)),
        )
        .join(DataSource, DataSource.id == WaterQualityObservation.source_id)
        .where(WaterQualityObservation.water_body_id == body.id)
        .group_by(DataSource.id)
    ).all()

    out = [
        {
            "key": key,
            "name": name,
            "organisation": organisation,
            "source_type": source_type,
            "observation_method": method,
            "expected_cadence": cadence,
            "reliability_note": note,
            "observation_count": count,
            "parameter_count": parameters,
            "first_observed_at": _as_utc(first).isoformat() if first else None,
            "latest_observed_at": _as_utc(last).isoformat() if last else None,
        }
        for (
            key,
            name,
            organisation,
            source_type,
            method,
            cadence,
            note,
            count,
            first,
            last,
            parameters,
        ) in rows
    ]
    out.sort(key=lambda s: s["latest_observed_at"] or "", reverse=True)
    return out


#: How long after its expected cadence a reachable source is still "Live".
#: Past this it is Stale -- reachable, but the data it holds is old.
STALE_AFTER_MULTIPLE = 3.0


def source_status(
    source: DataSource, *, records_held: int, now: datetime | None = None
) -> dict[str, Any]:
    """Classify one provider from its real fetch results.

    Four states, each computed rather than configured:

    ``live``          reachable, and its newest data is within cadence.
    ``stale``         reachable, but the data it holds has aged out.
    ``sync_paused``   the server answered and refused. Nothing is wrong on
                      this side and retrying harder will not help.
    ``unavailable``   it could not be reached at all.

    The distinction between the last two is the one worth drawing. A 403 is
    not an outage: the host is up, the handshake completed, and it declined.
    Reporting that as "Unavailable" invites someone to go looking for a
    network fault that is not there.
    """
    moment = now or datetime.now(UTC)
    error = source.last_error or ""
    last_success = _as_utc(source.last_success_at) if source.last_success_at else None

    if source.is_available:
        period = CADENCE_DAYS.get(source.expected_cadence)
        aged_out = bool(
            period
            and last_success
            and (moment - last_success).days > period * STALE_AFTER_MULTIPLE
        )
        state = "stale" if aged_out else "live"
        label = "Stale" if aged_out else "Live"
        detail = (
            "Reachable, but the most recent successful sync is older than "
            "this source's expected cadence."
            if aged_out
            else "Reachable, and syncing within its expected cadence."
        )
    elif "403" in error or "forbidden" in error.lower():
        state = "sync_paused"
        label = "Sync paused"
        detail = (
            "Blocked by upstream firewall: automated access refused "
            "(HTTP 403). Showing last successful sync "
            f"({_day(last_success)})."
        )
    else:
        state = "unavailable"
        label = "Unavailable"
        detail = (
            "The source could not be reached. Showing last successful sync "
            f"({_day(last_success)})."
        )

    return {
        "state": state,
        "label": label,
        "tone": {"live": "ok", "stale": "warn", "sync_paused": "warn"}.get(
            state, "bad"
        ),
        "detail": detail,
        "records_held": records_held,
        # The raw error belongs behind a toggle, not on the card: it is for
        # whoever is debugging, and it reads as breakage to everyone else.
        "technical_detail": error or None,
    }


def _day(moment: datetime | None) -> str:
    """A date for a sentence, or an honest absence."""
    return moment.strftime("%d %b %Y") if moment else "never"


def sources_for_body(db: Session, body: WaterBody) -> list[dict]:
    """Which sources contributed observations to this water body.

    Same cached summary as :func:`latest_by_source`, shaped for the provenance
    panel. The aggregate below is the fallback.
    """
    cached = summary_for(db, body)
    if cached.get("sources") is not None:
        return [
            {
                "key": entry["key"],
                "name": entry["name"],
                "organisation": entry["organisation"],
                "url": entry.get("url"),
                "dataset": entry.get("dataset"),
                "licence": entry.get("licence"),
                "expected_cadence": entry.get("expected_cadence"),
                "observation_count": entry.get("observation_count"),
                "latest_observed_at": entry.get("latest_observed_at"),
                "retrieved_at": entry.get("retrieved_at"),
            }
            for entry in cached["sources"]
        ]

    rows = db.execute(
        select(
            DataSource.key,
            DataSource.name,
            DataSource.organisation,
            DataSource.url,
            DataSource.dataset,
            DataSource.licence,
            DataSource.expected_cadence,
            func.count(WaterQualityObservation.id),
            func.max(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.retrieved_at),
        )
        .join(DataSource, DataSource.id == WaterQualityObservation.source_id)
        .where(WaterQualityObservation.water_body_id == body.id)
        .group_by(DataSource.id)
    ).all()

    return [
        {
            "key": key,
            "name": name,
            "organisation": organisation,
            "url": url,
            "dataset": dataset,
            "licence": licence,
            "expected_cadence": cadence,
            "observation_count": count,
            "latest_observed_at": (_as_utc(latest).isoformat() if latest else None),
            "retrieved_at": _as_utc(retrieved).isoformat() if retrieved else None,
        }
        for (
            key,
            name,
            organisation,
            url,
            dataset,
            licence,
            cadence,
            count,
            latest,
            retrieved,
        ) in rows
    ]


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------
def _trend_note(
    points: list[dict], trimmed: dict[str, int], all_points: list[dict]
) -> str | None:
    """What a reader needs to know about the series they are looking at."""
    if len(points) < 2:
        return "Fewer than two observations; no trend can be drawn."
    if not trimmed:
        return None
    parts = ", ".join(
        f"{source} has {total:,} measurements"
        for source, total in sorted(trimmed.items())
    )
    return (
        f"Showing the most recent {MAX_TREND_POINTS_PER_SOURCE:,} measurements "
        f"per source of {len(all_points):,} in total ({parts}). Each point is a "
        "measurement; none is averaged or interpolated."
    )


#: Most points returned per source in one trend. A chart a few hundred pixels
#: wide cannot show more, and the full count is always reported beside them.
MAX_TREND_POINTS_PER_SOURCE = 500


def _cap_per_source(
    points: list[dict], per_source: int
) -> tuple[list[dict], dict[str, int]]:
    """Keep each source's most recent points, in time order.

    Returns the kept points and, for each source that was trimmed, how many
    measurements it actually has. Nothing is averaged or interpolated: these
    are the same measurements, fewer of them.
    """
    by_source: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_source[point.get("source") or "unknown"].append(point)

    kept: list[dict] = []
    trimmed: dict[str, int] = {}
    for source, series in by_source.items():
        if len(series) > per_source:
            trimmed[source] = len(series)
            series = series[-per_source:]
        kept.extend(series)
    kept.sort(key=lambda p: p["observed_at"])
    return kept, trimmed


def parameter_trend(
    db: Session,
    slug: str,
    parameter: str,
    *,
    days: int | None = None,
) -> dict | None:
    """Time series for one parameter on one water body.

    Returns the points that exist. It never interpolates, never
    forward-fills, and never pads the range with zeros -- a gap in monitoring
    is information, and drawing a flat line across it would invent data.
    """
    body = db.scalar(select(WaterBody).where(WaterBody.slug == slug))
    if body is None:
        return None

    meta = BY_KEY.get(parameter)
    if meta is None:
        return None

    stmt = (
        select(
            WaterQualityObservation.observed_at,
            WaterQualityObservation.normalized_value,
            WaterQualityObservation.value,
            WaterQualityObservation.quality_flag,
            MonitoringStation.name,
            DataSource.key,
            DataSource.name,
        )
        .join(
            MonitoringStation,
            MonitoringStation.id == WaterQualityObservation.station_id,
        )
        .join(DataSource, DataSource.id == WaterQualityObservation.source_id)
        .where(
            WaterQualityObservation.water_body_id == body.id,
            WaterQualityObservation.parameter == parameter,
        )
        .order_by(WaterQualityObservation.observed_at)
    )

    rows = db.execute(stmt).all()
    all_points = [
        {
            "observed_at": _as_utc(observed_at).isoformat(),
            "value": normalized if normalized is not None else value,
            "station": station,
            "quality_flag": str(flag),
            # Two agencies sampling the same river are two series, never one
            # line: joining them would draw a trend nobody measured.
            "source": source_key,
            "source_name": source_name,
        }
        for observed_at, normalized, value, flag, station, source_key, source_name in rows
        if (normalized if normalized is not None else value) is not None
    ]

    # Keep each agency's most recent points. Capping the combined series
    # instead would drop whole sources: the Ganga's newest 1,500 readings are
    # all sensor and recent CWC data, and CPCB's line -- the reason the chart
    # separates sources at all -- would vanish without a word.
    points, trimmed = _cap_per_source(all_points, MAX_TREND_POINTS_PER_SOURCE)

    if days is not None and points:
        cutoff = datetime.now(UTC).timestamp() - days * 86400
        points = [
            p
            for p in points
            if datetime.fromisoformat(p["observed_at"]).timestamp() >= cutoff
        ]

    values = [p["value"] for p in points]
    return {
        "water_body": body.name,
        "slug": body.slug,
        "parameter": parameter,
        "label": meta.label,
        "unit": meta.unit,
        "family": str(meta.family),
        "higher_is_worse": meta.higher_is_worse,
        # point_count is what came back; measured_count is what exists. They
        # differ when a long series was trimmed for the chart, and the
        # difference is stated rather than left for a reader to notice.
        "point_count": len(points),
        "measured_count": len(all_points),
        "truncated": bool(trimmed),
        "truncated_sources": trimmed,
        "max_points_per_source": MAX_TREND_POINTS_PER_SOURCE,
        "points": points,
        "first_observed_at": points[0]["observed_at"] if points else None,
        "last_observed_at": points[-1]["observed_at"] if points else None,
        "measured_from": all_points[0]["observed_at"] if all_points else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": round(sum(values) / len(values), 3) if values else None,
        "sufficient": len(points) >= 2,
        "note": _trend_note(points, trimmed, all_points),
    }


def available_parameters(db: Session, slug: str) -> list[dict]:
    """Which parameters have enough history on this body to plot.

    From the cached summary when it is current; the aggregate below is the
    fallback, and costs 104 ms on the Ganga.
    """
    body = db.scalar(select(WaterBody).where(WaterBody.slug == slug))
    if body is None:
        return []

    cached = summary_for(db, body)
    if cached.get("parameters"):
        out = []
        for entry in cached["parameters"]:
            meta = BY_KEY.get(entry["parameter"])
            if meta is None:
                continue
            out.append(
                {
                    "parameter": entry["parameter"],
                    "label": meta.label,
                    "family": str(meta.family),
                    "unit": meta.unit,
                    "point_count": entry["point_count"],
                    "first_observed_at": entry["first_observed_at"],
                    "last_observed_at": entry["last_observed_at"],
                    "plottable": entry["point_count"] >= 2,
                }
            )
        return out

    rows = db.execute(
        select(
            WaterQualityObservation.parameter,
            func.count(WaterQualityObservation.id),
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
        )
        .where(WaterQualityObservation.water_body_id == body.id)
        .group_by(WaterQualityObservation.parameter)
    ).all()

    out = []
    for parameter, count, first, last in rows:
        meta = BY_KEY.get(parameter)
        if meta is None:
            continue
        out.append(
            {
                "parameter": parameter,
                "label": meta.label,
                "family": str(meta.family),
                "unit": meta.unit,
                "point_count": count,
                "first_observed_at": _as_utc(first).isoformat() if first else None,
                "last_observed_at": _as_utc(last).isoformat() if last else None,
                "plottable": count >= 2,
            }
        )
    order = {"biological": 0, "chemical": 1, "physical": 2}
    return sorted(out, key=lambda p: (order.get(p["family"], 3), p["label"]))


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def map_water_bodies(
    db: Session, filters: WaterBodyFilters, *, limit: int = MAP_FEATURE_LIMIT
) -> list[dict]:
    """Water bodies as map features within a viewport."""
    stmt = _apply_filters(select(WaterBody), filters).where(
        WaterBody.centroid_lat.is_not(None),
        WaterBody.centroid_lon.is_not(None),
    )
    rows = db.scalars(
        stmt.order_by(WaterBody.observation_count.desc()).limit(limit)
    ).all()

    return [
        {
            "id": b.id,
            "slug": b.slug,
            "name": b.name,
            "water_type": str(b.water_type),
            "latitude": b.centroid_lat,
            "longitude": b.centroid_lon,
            "status": b.cached_status,
            "latest_available_status": b.cached_historical_status,
            "station_count": b.station_count,
            "observation_count": b.observation_count,
            "latest_observed_at": (
                _as_utc(b.latest_observed_at).isoformat()
                if b.latest_observed_at
                else None
            ),
            "has_geometry": b.geometry_status == "matched",
        }
        for b in rows
    ]


def map_stations(
    db: Session,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    state: str | None = None,
    limit: int = MAP_FEATURE_LIMIT,
) -> list[dict]:
    """Monitoring stations as map features."""
    stmt = select(MonitoringStation).where(
        MonitoringStation.latitude.is_not(None),
        MonitoringStation.longitude.is_not(None),
        MonitoringStation.geo_quality != "missing",
    )
    if bbox:
        min_lat, min_lon, max_lat, max_lon = bbox
        stmt = stmt.where(
            MonitoringStation.latitude >= min_lat,
            MonitoringStation.latitude <= max_lat,
            MonitoringStation.longitude >= min_lon,
            MonitoringStation.longitude <= max_lon,
        )
    if state:
        stmt = stmt.join(State, MonitoringStation.state_id == State.id).where(
            or_(
                func.lower(State.slug) == state.lower(),
                func.upper(State.code) == state.upper(),
            )
        )

    rows = db.scalars(
        stmt.order_by(MonitoringStation.observation_count.desc()).limit(limit)
    ).all()
    return summarise_stations(db, list(rows))


# ---------------------------------------------------------------------------
# Spatial search
# ---------------------------------------------------------------------------
def water_bodies_near(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: float,
    *,
    limit: int = 50,
    water_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Water bodies within ``radius_km`` of a point.

    Two stages on purpose. A bounding box in SQL uses the lat/lon index to
    discard almost everything cheaply; the exact haversine distance then runs
    in Python over the survivors. Skipping the second stage would return a
    square, which is what "within 10 km" must not mean.
    """
    from app.services import spatial

    ids = spatial.bodies_within_radius(
        db,
        latitude,
        longitude,
        radius_km,
        water_type=water_type,
        status=status,
        limit=limit,
    )
    if ids is not None:
        # PostGIS did the circle on an index; only the chosen rows load.
        bodies = {
            b.id: b
            for b in db.scalars(
                select(WaterBody).where(WaterBody.id.in_([i for i, _ in ids]))
            )
        }
        lookups = preload(db, bodies=list(bodies.values()))
        return [
            {**summarise_body(db, bodies[i], lookups=lookups), "distance_km": km}
            for i, km in ids
            if i in bodies
        ]

    lat_delta = radius_km / 110.574
    # Longitude degrees shorten towards the poles; guard the cosine so a
    # near-polar query cannot divide by zero.
    lon_delta = radius_km / max(111.320 * math.cos(math.radians(latitude)), 0.01)

    stmt = select(WaterBody).where(
        WaterBody.centroid_lat.is_not(None),
        WaterBody.centroid_lon.is_not(None),
        WaterBody.centroid_lat.between(latitude - lat_delta, latitude + lat_delta),
        WaterBody.centroid_lon.between(longitude - lon_delta, longitude + lon_delta),
    )
    if water_type:
        stmt = stmt.where(WaterBody.water_type == water_type)
    if status:
        stmt = stmt.where(WaterBody.cached_status == status)

    candidates = db.scalars(stmt.limit(limit * 10)).all()
    lookups = preload(db, bodies=list(candidates))

    out: list[dict] = []
    for body in candidates:
        distance = haversine_km(latitude, longitude, body.centroid_lat, body.centroid_lon)
        if distance <= radius_km:
            out.append(
                {
                    **summarise_body(db, body, lookups=lookups),
                    "distance_km": round(distance, 2),
                }
            )

    out.sort(key=lambda b: b["distance_km"])
    return out[:limit]


def water_bodies_near_districts(
    db: Session,
    district_ids: list[int],
    radius_km: float,
    *,
    limit: int = 100,
) -> list[dict]:
    """Water bodies within ``radius_km`` of any station in the given districts.

    "Near Bengaluru" is not "near one point". The source publishes no district
    boundary, and a district centroid computed from scattered stations can sit
    well away from the city -- averaging Bangalore Urban and Bangalore Rural
    put the centre 56 km from Bellandur Lake. So the district is represented
    by its own monitoring stations, and a water body qualifies if it is within
    the radius of any of them. ``distance_km`` is to the nearest such station.
    """
    points = [
        (lat, lon)
        for lat, lon in db.execute(
            select(MonitoringStation.latitude, MonitoringStation.longitude).where(
                MonitoringStation.district_id.in_(district_ids),
                MonitoringStation.latitude.is_not(None),
                MonitoringStation.longitude.is_not(None),
                MonitoringStation.geo_quality == "ok",
            )
        )
    ]
    if not points:
        return []

    lat_pad = radius_km / 110.574
    mid_lat = sum(p[0] for p in points) / len(points)
    lon_pad = radius_km / max(111.320 * math.cos(math.radians(mid_lat)), 0.01)
    min_lat = min(p[0] for p in points) - lat_pad
    max_lat = max(p[0] for p in points) + lat_pad
    min_lon = min(p[1] for p in points) - lon_pad
    max_lon = max(p[1] for p in points) + lon_pad

    candidates = db.scalars(
        select(WaterBody).where(
            WaterBody.centroid_lat.between(min_lat, max_lat),
            WaterBody.centroid_lon.between(min_lon, max_lon),
        )
    ).all()
    lookups = preload(db, bodies=list(candidates))

    out: list[dict] = []
    for body in candidates:
        nearest = min(
            haversine_km(lat, lon, body.centroid_lat, body.centroid_lon)
            for lat, lon in points
        )
        if nearest <= radius_km:
            out.append(
                {
                    **summarise_body(db, body, lookups=lookups),
                    "distance_km": round(nearest, 2),
                }
            )

    out.sort(key=lambda b: b["distance_km"])
    return out[:limit]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search(db: Session, query: str, *, limit: int = SEARCH_LIMIT) -> list[dict]:
    """Unified search over water bodies, states, districts and stations.

    Deterministic and lexical. Results carry their type so the UI can route a
    click correctly, and a water-body hit carries the date of its latest
    observation so a searcher sees immediately whether the data is current.
    """
    text = (query or "").strip()
    if len(text) < 2:
        return []

    needle = f"%{text.lower()}%"
    normalised = f"%{normalise_name(text)}%"
    results: list[dict] = []

    for body in db.scalars(
        select(WaterBody)
        .where(
            or_(
                func.lower(WaterBody.name).like(needle),
                WaterBody.normalized_name.like(normalised),
            )
        )
        .order_by(WaterBody.observation_count.desc())
        .limit(limit)
    ):
        summary = summarise_body(db, body)
        results.append(
            {
                "type": "water_body",
                "title": body.name,
                "subtitle": " · ".join(
                    x for x in [summary["district"], summary["state"]] if x
                ),
                "slug": body.slug,
                "href": f"/app/water/{body.slug}",
                "water_type": str(body.water_type),
                "status": body.cached_status,
                "latest_available_status": body.cached_historical_status,
                "latest_observed_at": summary["latest_observed_at"],
                "latitude": body.centroid_lat,
                "longitude": body.centroid_lon,
                "rank": body.observation_count,
            }
        )

    from app.models.water_geo import City

    key = normalise_name(text)
    for city in db.scalars(select(City)):
        names = [city.name, *(city.aliases or [])]
        if not any(key in normalise_name(n) for n in names):
            continue
        state = db.get(State, city.state_id) if city.state_id else None
        results.append(
            {
                "type": "city",
                "title": city.name,
                "subtitle": f"City · {state.name}" if state else "City",
                "slug": city.slug,
                "href": f"/app/city/{city.slug}",
                "latitude": city.centroid_lat,
                "longitude": city.centroid_lon,
                "bbox": (
                    [city.min_lat, city.min_lon, city.max_lat, city.max_lon]
                    if city.min_lat is not None
                    else None
                ),
                "rank": 11_000,
            }
        )

    for state in db.scalars(
        select(State).where(func.lower(State.name).like(needle)).limit(5)
    ):
        results.append(
            {
                "type": "state",
                "title": state.name,
                "subtitle": "State",
                "slug": state.slug,
                "href": f"/app/state/{state.slug}",
                "rank": 10_000,
            }
        )

    # A district can be searched by its official alternative name, so
    # "Bengaluru" finds the source's "Bangalore Urban".
    place_terms = [needle] + [
        f"%{alt.lower()}%" for alt in PLACE_ALIASES.get(normalise_name(text), ())
    ]
    for district, state_name in db.execute(
        select(District, State.name)
        .join(State, State.id == District.state_id)
        .where(or_(*(func.lower(District.name).like(t) for t in place_terms)))
        .limit(8)
    ):
        results.append(
            {
                "type": "district",
                "title": district.name,
                "subtitle": f"District · {state_name}",
                "slug": district.slug,
                "href": f"/app/city/{district.slug}",
                "latitude": district.centroid_lat,
                "longitude": district.centroid_lon,
                "rank": 9_000,
            }
        )

    for station in db.scalars(
        select(MonitoringStation)
        .where(func.lower(MonitoringStation.name).like(needle))
        .order_by(MonitoringStation.observation_count.desc())
        .limit(8)
    ):
        results.append(
            {
                "type": "station",
                "title": station.name,
                "subtitle": "Monitoring station",
                "slug": station.slug,
                "href": f"/app/stations/{station.id}",
                "latitude": station.latitude,
                "longitude": station.longitude,
                "rank": station.observation_count,
            }
        )

    # Exact-prefix matches first, then by how much data backs the result.
    lowered = text.lower()
    results.sort(
        key=lambda r: (
            0 if str(r["title"]).lower().startswith(lowered) else 1,
            -int(r.get("rank") or 0),
        )
    )
    return results[:limit]


# ---------------------------------------------------------------------------
# Geography roll-ups
# ---------------------------------------------------------------------------
def status_distribution(
    db: Session, *, state: str | None = None, historical: bool = False
) -> dict[str, int]:
    """How many water bodies sit in each status band.

    ``historical=False`` counts present-tense statuses; ``historical=True``
    counts what each body's most recent measurement found. The two must never
    share a label: a chart titled "when last measured" fed from present-tense
    data shows every body as "no recent data" and contradicts its own heading.
    """
    column = WaterBody.cached_historical_status if historical else WaterBody.cached_status
    stmt = select(column, func.count(WaterBody.id))
    if state:
        stmt = stmt.where(WaterBody.id.in_(bodies_in_state(state)))
    rows = db.execute(stmt.group_by(column)).all()
    return {(status or "UNKNOWN"): count for status, count in rows}


def list_states(db: Session) -> list[dict]:
    """States with counts, for the India page."""
    # Counted through stations so a river crossing several states is counted
    # in each state it is monitored in.
    rows = db.execute(
        select(
            State,
            func.count(func.distinct(MonitoringStation.water_body_id)),
            func.count(func.distinct(MonitoringStation.id)),
            func.max(MonitoringStation.latest_observed_at),
        )
        .outerjoin(MonitoringStation, MonitoringStation.state_id == State.id)
        .group_by(State.id)
        .order_by(State.name)
    ).all()

    out = []
    for state, body_count, stations, latest in rows:
        out.append(
            {
                "code": state.code,
                "name": state.name,
                "slug": state.slug,
                "water_body_count": body_count or 0,
                "station_count": stations or 0,
                "latest_observed_at": (_as_utc(latest).isoformat() if latest else None),
            }
        )
    return out


def state_detail(db: Session, slug: str) -> dict | None:
    """Everything the state page shows, all derived from ingested data."""
    state = db.scalar(
        select(State).where(
            or_(
                func.lower(State.slug) == slug.lower(),
                func.upper(State.code) == slug.upper(),
            )
        )
    )
    if state is None:
        return None

    bodies = db.scalars(
        select(WaterBody).where(WaterBody.id.in_(bodies_in_state(state.slug)))
    ).all()
    by_type: dict[str, int] = defaultdict(int)
    for body in bodies:
        by_type[str(body.water_type)] += 1

    stations = db.scalar(
        select(func.count(MonitoringStation.id)).where(
            MonitoringStation.state_id == state.id
        )
    )
    latest_in_state = db.scalar(
        select(func.max(MonitoringStation.latest_observed_at)).where(
            MonitoringStation.state_id == state.id
        )
    )

    # Observations taken at stations in this state -- not every observation
    # of every river that happens to touch it.
    observations = db.scalar(
        select(func.count(WaterQualityObservation.id))
        .join(
            MonitoringStation,
            MonitoringStation.id == WaterQualityObservation.station_id,
        )
        .where(MonitoringStation.state_id == state.id)
    )

    districts = db.execute(
        select(District, func.count(func.distinct(MonitoringStation.water_body_id)))
        .outerjoin(MonitoringStation, MonitoringStation.district_id == District.id)
        .where(District.state_id == state.id)
        .group_by(District.id)
        .order_by(District.name)
    ).all()

    # Rank by what the last measurement found. Ranking by the present-tense
    # status would sort on a column that is "no recent data" for every row.
    ranked = sorted(
        bodies,
        key=lambda b: (
            -status_rank(WaterStatus(b.cached_historical_status))
            if b.cached_historical_status
            else 0,
            -b.observation_count,
        ),
    )

    return {
        "code": state.code,
        "name": state.name,
        "slug": state.slug,
        "water_body_count": len(bodies),
        "station_count": stations or 0,
        "observation_count": observations or 0,
        "latest_observed_at": (
            _as_utc(latest_in_state).isoformat() if latest_in_state else None
        ),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "status_distribution": status_distribution(db, state=state.slug),
        "historical_status_distribution": status_distribution(
            db, state=state.slug, historical=True
        ),
        "districts": [
            {
                "name": d.name,
                "slug": d.slug,
                "water_body_count": c or 0,
                "latitude": d.centroid_lat,
                "longitude": d.centroid_lon,
            }
            for d, c in districts
        ],
        "notable": summarise_bodies(db, ranked[:12], include_state=False),
    }


def district_detail(db: Session, slug: str) -> dict | None:
    """City/district page payload."""
    row = db.execute(
        select(District, State)
        .join(State, State.id == District.state_id)
        .where(func.lower(District.slug) == slug.lower())
    ).first()
    if row is None:
        return None
    district, state = row

    in_district = (
        select(MonitoringStation.water_body_id)
        .where(
            MonitoringStation.district_id == district.id,
            MonitoringStation.water_body_id.is_not(None),
        )
        .distinct()
    )
    bodies = db.scalars(
        select(WaterBody)
        .where(WaterBody.id.in_(in_district))
        .order_by(WaterBody.observation_count.desc())
    ).all()
    stations = db.scalars(
        select(MonitoringStation)
        .where(MonitoringStation.district_id == district.id)
        .order_by(MonitoringStation.observation_count.desc())
    ).all()

    by_type: dict[str, int] = defaultdict(int)
    for body in bodies:
        by_type[str(body.water_type)] += 1

    return {
        "name": district.name,
        "slug": district.slug,
        "state": state.name,
        "state_slug": state.slug,
        "latitude": district.centroid_lat,
        "longitude": district.centroid_lon,
        "water_body_count": len(bodies),
        "station_count": len(stations),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "water_bodies": summarise_bodies(db, list(bodies[:60])),
        "stations": summarise_stations(db, list(stations[:60])),
    }


# ---------------------------------------------------------------------------
# Platform overview
# ---------------------------------------------------------------------------
#: A water body is described in the present tense only if its newest
#: observation is this recent. Two days, because the only sub-daily source in
#: India that this platform can reach reports hourly, and a station that has
#: not reported for two days has stopped reporting.
#:
#: Taken from the freshness engine rather than restated, so that this count and
#: the pages it counts always agree. When they were two separate numbers the
#: overview said the Ganga had current data while the Ganga's own page said its
#: reading was too old to describe the river.
CURRENT_DATA_DAYS = int(MIN_NO_RECENT_DAYS)

#: Newer than a monthly programme's own cadence allows for, but not current.
RECENT_DATA_DAYS = 90


def coverage_counts(db: Session) -> dict:
    """How many water bodies have current data, recent data, or only history.

    The single most important number on the platform is the first one: 26 of
    2,740. Reporting it as a count, next to the others, is what stops the
    map looking like a live national network.
    """
    now = datetime.now(UTC)
    current_cutoff = now - timedelta(days=CURRENT_DATA_DAYS)
    recent_cutoff = now - timedelta(days=RECENT_DATA_DAYS)

    def count(condition: ColumnElement[bool]) -> int:
        return db.scalar(select(func.count(WaterBody.id)).where(condition)) or 0

    total = db.scalar(select(func.count(WaterBody.id))) or 0
    no_data = count(WaterBody.latest_observed_at.is_(None))
    current = count(WaterBody.latest_observed_at >= current_cutoff)
    recent = (
        count(
            WaterBody.latest_observed_at.is_not(None),
        )
        - count(WaterBody.latest_observed_at < recent_cutoff)
        - current
    )
    historical = total - no_data - current - max(recent, 0)

    return {
        "total": total,
        "current": current,
        "recent": max(recent, 0),
        "historical_only": max(historical, 0),
        "no_data": no_data,
        "current_within_days": CURRENT_DATA_DAYS,
        "recent_within_days": RECENT_DATA_DAYS,
        "note": (
            f"{current} of {total} water bodies have an observation from the "
            f"last {CURRENT_DATA_DAYS} days. The rest are described by their "
            "most recent measurement, with its date; none of those is a "
            "statement about today."
        ),
    }


def data_availability(db: Session, body: WaterBody) -> dict:
    """What kinds of knowledge exist for this water body, as plain answers.

    Absence is the point: a reader should be able to see that there is no
    real-time data and no official classification without inferring it from
    an empty panel.
    """
    from app.models.water_geo import SourceClassification, WaterBodyGeometry, WaterImage

    summary = summary_for(db, body)
    sources = summary.get("sources") or []
    newest = sources[0] if sources else None
    latest = body.latest_observed_at
    age_days = (
        round((datetime.now(UTC) - _as_utc(latest)).total_seconds() / 86400.0, 1)
        if latest
        else None
    )
    is_current = age_days is not None and age_days <= CURRENT_DATA_DAYS

    has_geometry = (
        db.scalar(
            select(WaterBodyGeometry.id).where(WaterBodyGeometry.water_body_id == body.id)
        )
        is not None
    )
    has_imagery = (
        db.scalar(select(WaterImage.id).where(WaterImage.water_body_id == body.id))
        is not None
    )
    has_classification = (
        db.scalar(
            select(SourceClassification.id).where(
                SourceClassification.water_body_id == body.id
            )
        )
        is not None
    )

    return {
        "real_time": is_current,
        "real_time_detail": (
            f"{newest['name']} reported {age_days:g} days ago"
            if is_current and newest
            else "No source reports this water body often enough to describe it now"
        ),
        "latest_measurement": _iso(latest),
        "latest_source": newest["name"] if newest else None,
        "age_days": age_days,
        "historical": bool(sources),
        "historical_detail": (
            f"{len(sources)} source{'s' if len(sources) != 1 else ''}, "
            f"{body.observation_count:,} observations"
            if sources
            else "No observation has ever been recorded"
        ),
        "geometry": has_geometry,
        "satellite_evidence": has_imagery,
        "official_classification": has_classification,
        "parameters_measured": summary.get("parameter_count", 0),
    }


def overview(db: Session) -> dict:
    """Headline counters for the dashboard.

    Every number is a count of ingested records. Nothing here is a target, an
    estimate or a placeholder, and the counts of water bodies *without* recent
    data are reported alongside the flattering ones.
    """
    total_bodies = db.scalar(select(func.count(WaterBody.id))) or 0
    total_stations = db.scalar(select(func.count(MonitoringStation.id))) or 0
    total_obs = db.scalar(select(func.count(WaterQualityObservation.id))) or 0
    latest = db.scalar(select(func.max(WaterQualityObservation.observed_at)))

    distribution = status_distribution(db)
    sources = db.scalars(select(DataSource)).all()
    # One query for every source's record count, rather than one per card.
    records_by_source = {
        source_id: count
        for source_id, count in db.execute(
            select(
                WaterQualityObservation.source_id,
                func.count(WaterQualityObservation.id),
            ).group_by(WaterQualityObservation.source_id)
        ).all()
    }
    last_run = db.scalar(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)
    )

    return {
        "water_bodies": total_bodies,
        "monitoring_stations": total_stations,
        "observations": total_obs,
        "states_covered": db.scalar(select(func.count(State.id))) or 0,
        "districts_covered": db.scalar(select(func.count(District.id))) or 0,
        "latest_observation_at": _as_utc(latest).isoformat() if latest else None,
        "status_distribution": distribution,
        "historical_status_distribution": status_distribution(db, historical=True),
        "without_recent_data": distribution.get(str(WaterStatus.NO_RECENT_DATA), 0),
        # The four-way split, so "26 of 2,740" is a number the page can show
        # rather than something a reader has to work out.
        "coverage": coverage_counts(db),
        # Records actually held per source. "Sync paused" is far easier to
        # read next to the number of measurements already in hand.
        "sources": [
            {
                "key": s.key,
                "name": s.name,
                "organisation": s.organisation,
                "is_available": s.is_available,
                "expected_cadence": s.expected_cadence,
                "last_success_at": (
                    _as_utc(s.last_success_at).isoformat() if s.last_success_at else None
                ),
                "last_error": s.last_error,
                "status": source_status(
                    s, records_held=records_by_source.get(s.id, 0)
                ),
            }
            for s in sources
        ],
        # Every external source this platform reads, not just the three
        # Indian water providers. A page headed "where the platform's
        # numbers come from" that omits six of nine is not answering its
        # own question.
        "external_providers": external_providers(db),
        "last_ingestion": (
            {
                "run_id": last_run.run_id,
                "source": last_run.source_key,
                "status": last_run.status,
                "records_inserted": last_run.records_inserted,
                "started_at": _as_utc(last_run.started_at).isoformat(),
                "finished_at": (
                    _as_utc(last_run.finished_at).isoformat()
                    if last_run.finished_at
                    else None
                ),
            }
            if last_run
            else None
        ),
    }


def job_runs(db: Session, *, limit: int = 20, job_type: str | None = None) -> dict:
    """Recent job runs plus, per job type, when it last succeeded.

    The second half is the part worth having: a list of runs says what
    happened, but "ingestion last succeeded 9 hours ago, satellite 6 days ago"
    is what tells you whether the data behind the pages is being maintained.
    """
    from app.models.water import IngestionRun

    query = select(IngestionRun).order_by(IngestionRun.started_at.desc())
    if job_type:
        query = query.where(IngestionRun.job_type == job_type)
    rows = db.scalars(query.limit(limit)).all()

    last_success = {
        row.job_type: _as_utc(row.last_success).isoformat()
        for row in db.execute(
            select(
                IngestionRun.job_type,
                func.max(IngestionRun.finished_at).label("last_success"),
            )
            .where(IngestionRun.status == "success")
            .group_by(IngestionRun.job_type)
        ).all()
        if row.last_success is not None
    }

    return {
        "last_success_by_job": last_success,
        "runs": [
            {
                "job_id": run.run_id,
                "job_type": run.job_type,
                "source": run.source_key,
                "status": run.status,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
                "duration_seconds": (
                    round((run.finished_at - run.started_at).total_seconds(), 1)
                    if run.finished_at and run.started_at
                    else None
                ),
                "records_seen": run.records_seen,
                "records_inserted": run.records_inserted,
                "records_updated": run.records_updated,
                "records_skipped": run.records_skipped,
                "records_duplicate": run.records_duplicate,
                "records_rejected": run.records_rejected,
                "errors": run.errors or [],
            }
            for run in rows
        ],
    }


def _iso(value: datetime | None) -> str | None:
    """Timestamp as UTC ISO-8601, or None."""
    converted = _as_utc(value) if value else None
    return converted.isoformat() if converted else None


def data_quality(db: Session) -> dict[str, Any]:
    """Counts by quality flag, so data problems are visible not hidden."""
    rows = db.execute(
        select(
            WaterQualityObservation.quality_flag,
            func.count(WaterQualityObservation.id),
        ).group_by(WaterQualityObservation.quality_flag)
    ).all()

    geo = db.execute(
        select(MonitoringStation.geo_quality, func.count(MonitoringStation.id)).group_by(
            MonitoringStation.geo_quality
        )
    ).all()

    unmatched = db.scalar(
        select(func.count(MonitoringStation.id)).where(
            MonitoringStation.water_body_id.is_(None)
        )
    )

    return {
        "observations_by_flag": {str(flag): count for flag, count in rows},
        "stations_by_geo_quality": {str(q): c for q, c in geo},
        "stations_without_water_body": unmatched or 0,
        "notes": [
            "Records that fail validation are flagged and kept, never "
            "silently dropped, so problems stay countable.",
            "A station without a water body is one whose name did not "
            "identify one; its observations are still stored.",
        ],
    }
