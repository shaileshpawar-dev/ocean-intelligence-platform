"""Water-data ingestion pipeline.

    SOURCE -> FETCH -> VALIDATE -> NORMALISE -> GEOCODE -> MATCH
           -> DEDUPLICATE -> PERSIST -> DENORMALISE -> LOG

Every stage is counted and the counts are written to an
:class:`~app.models.water.IngestionRun` row. That matters more than it might
look: a source that silently starts returning half as many rows is otherwise
invisible until a user notices a gap, whereas here it shows up as a step
change in ``records_inserted`` against the previous run.

Three decisions worth stating plainly:

**Nothing malformed is discarded.** A value that will not parse is stored
with ``quality_flag = INVALID`` and its raw text preserved. Dropping it would
make the problem unobservable; keeping it means the data-quality view can
count it and someone can go and look.

**Re-running is safe.** Observations are keyed by
``(station, parameter, observed_at)``. A second run over the same resource
inserts nothing new, so ingestion can be retried after a partial failure
without creating duplicates.

**A failed source fails loudly.** When a provider raises, the run is recorded
as ``failed`` with the error text and the data source is marked unavailable.
The platform then serves the last successfully ingested data and says so,
rather than presenting a gap as if it were reality.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import QualityFlag, WaterEvidenceType
from app.models.water import (
    DataSource,
    District,
    IngestionRun,
    MonitoringStation,
    State,
    WaterBody,
    WaterQualityObservation,
)
from app.water.matching import (
    MatchResult,
    apply_propagation,
    haversine_km,
    is_plausible_merge,
    merge_key,
    normalise_name,
    propagate_types,
    resolve,
    slugify,
)
from app.water.providers import ObservationRow, ProviderUnavailableError, get_provider
from app.water.providers.base import FetchPlan, WaterDataProvider

logger = get_logger(__name__)

# Validation bounds. Deliberately wide: the intent is to catch transcription
# errors -- a pH of 780, a negative coliform count -- not to second-guess a
# genuinely extreme but real measurement in a heavily polluted urban river.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "ph": (0.0, 14.0),
    "temperature": (-5.0, 60.0),
    "dissolved_oxygen": (0.0, 25.0),
    "bod": (0.0, 2000.0),
    "cod": (0.0, 10000.0),
    "turbidity": (0.0, 100000.0),
    "fecal_coliform": (0.0, 1e9),
    "total_coliform": (0.0, 1e9),
    "electrical_conductivity": (0.0, 1e6),
}


def _new_run_id() -> str:
    """Identifier for one ingestion execution."""
    return uuid.uuid4().hex[:16]


def _as_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime read back from the database to aware UTC.

    SQLite has no timezone-aware storage, so a column declared
    ``DateTime(timezone=True)`` round-trips as a *naive* datetime while the
    provider supplies an aware one. Comparing the two silently never matches,
    which made the de-duplication key miss on every re-run and turned a
    repeat ingestion into a unique-constraint crash. Normalising both sides
    here is what makes ingestion genuinely idempotent on SQLite as well as
    Postgres.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validate(row: ObservationRow) -> tuple[QualityFlag, list[str]]:
    """Apply validation rules, returning a flag and the notes explaining it."""
    notes = list(row.quality_flags)

    if row.value is None and row.qualitative_value is None:
        return QualityFlag.INVALID, [*notes, "no_value"]

    if "unparseable" in notes:
        return QualityFlag.INVALID, notes

    if row.value is not None:
        bounds = PLAUSIBLE_RANGES.get(row.parameter_key)
        if bounds and not (bounds[0] <= row.value <= bounds[1]):
            notes.append(f"outside_plausible_range[{bounds[0]},{bounds[1]}]")
            return QualityFlag.SUSPECT, notes

    if notes:
        return QualityFlag.SUSPECT, notes
    return QualityFlag.OK, notes


class _Registry:
    """Per-run cache of the lookup entities.

    Ingestion touches the same handful of states and districts thousands of
    times. Without this the pipeline issues a SELECT per row and spends most
    of its time in the database driver.
    """

    def __init__(self, db: Session, source: DataSource) -> None:
        self.db = db
        self.source = source
        self.states: dict[str, State] = {}
        self.districts: dict[tuple[int, str], District] = {}
        self.bodies: dict[tuple[str, str, str], WaterBody] = {}
        self.stations: dict[str, MonitoringStation] = {}
        self.created_bodies = 0
        self.created_stations = 0

    def state(self, name: str | None, code: str | None) -> State | None:
        """Get or create a state."""
        if not code and not name:
            return None
        key = (code or normalise_name(name or ""))[:4].upper()
        if key in self.states:
            return self.states[key]

        found = self.db.scalar(select(State).where(State.code == key))
        if found is None:
            label = name or key
            found = State(code=key, name=label, slug=slugify(label))
            self.db.add(found)
            self.db.flush()
        self.states[key] = found
        return found

    def district(self, state: State | None, name: str | None) -> District | None:
        """Get or create a district within a state."""
        if state is None or not name:
            return None
        slug = slugify(name)
        key = (state.id, slug)
        if key in self.districts:
            return self.districts[key]

        found = self.db.scalar(
            select(District).where(District.state_id == state.id, District.slug == slug)
        )
        if found is None:
            found = District(state_id=state.id, name=name, slug=slug)
            self.db.add(found)
            self.db.flush()
        self.districts[key] = found
        return found

    def water_body(
        self,
        match: MatchResult,
        state: State | None,
        district: District | None,
        latitude: float | None,
        longitude: float | None,
    ) -> WaterBody | None:
        """Get or create the water body a station belongs to.

        Applies the geographic guard: a same-named body whose centroid is
        implausibly far away starts a new, state-qualified record instead of
        merging two different rivers that happen to share a name.
        """
        if not match.is_identified:
            return None

        key = merge_key(match, state.code if state else None)
        found = self.bodies.get(key)

        if found is None:
            stmt = select(WaterBody).where(
                WaterBody.normalized_name == match.normalized_name,
                WaterBody.water_type == match.water_type,
            )
            if key[2]:
                stmt = stmt.where(WaterBody.state_id == (state.id if state else None))
            found = self.db.scalar(stmt)

        if found is not None and not is_plausible_merge(
            latitude, longitude, found.centroid_lat, found.centroid_lon
        ):
            # Same name, too far away to be the same feature.
            qualifier = state.name if state else "Unknown"
            found = self.db.scalar(
                select(WaterBody).where(
                    WaterBody.normalized_name == match.normalized_name,
                    WaterBody.water_type == match.water_type,
                    WaterBody.state_id == (state.id if state else None),
                )
            )
            if found is None:
                found = self._create_body(
                    match,
                    state,
                    district,
                    latitude,
                    longitude,
                    name=f"{match.name} ({qualifier})",
                )

        if found is None:
            found = self._create_body(
                match, state, district, latitude, longitude, name=match.name
            )

        self.bodies[key] = found
        return found

    def _create_body(
        self,
        match: MatchResult,
        state: State | None,
        district: District | None,
        latitude: float | None,
        longitude: float | None,
        *,
        name: str,
    ) -> WaterBody:
        """Insert a new water body with a collision-free slug."""
        base = slugify(name)
        slug = base
        suffix = 2
        while self.db.scalar(select(WaterBody.id).where(WaterBody.slug == slug)):
            slug = f"{base}-{suffix}"
            suffix += 1

        body = WaterBody(
            slug=slug,
            name=name,
            normalized_name=match.normalized_name,
            water_type=match.water_type,
            state_id=state.id if state else None,
            district_id=district.id if district else None,
            centroid_lat=latitude,
            centroid_lon=longitude,
            aliases=[],
            match_confidence=match.confidence,
            match_method=match.method,
        )
        self.db.add(body)
        self.db.flush()
        self.created_bodies += 1
        return body

    def station(
        self,
        row: ObservationRow,
        body: WaterBody | None,
        state: State | None,
        district: District | None,
    ) -> MonitoringStation:
        """Get or create the monitoring station a row came from."""
        code = normalise_name(row.station_name)[:160]
        if code in self.stations:
            return self.stations[code]

        found = self.db.scalar(
            select(MonitoringStation).where(
                MonitoringStation.source_id == self.source.id,
                MonitoringStation.station_code == code,
            )
        )
        if found is None:
            geo_quality = "ok"
            if row.latitude is None or row.longitude is None:
                geo_quality = "missing"
            elif "coordinates_outside_india" in row.quality_flags:
                geo_quality = "suspect"

            found = MonitoringStation(
                station_code=code,
                name=row.station_name,
                slug=slugify(row.station_name)[:300],
                source_id=self.source.id,
                water_body_id=body.id if body else None,
                state_id=state.id if state else None,
                district_id=district.id if district else None,
                agency=row.agency,
                tehsil=row.tehsil,
                village=row.village,
                latitude=row.latitude,
                longitude=row.longitude,
                geo_quality=geo_quality,
            )
            self.db.add(found)
            self.db.flush()
            self.created_stations += 1
        elif found.water_body_id is None and body is not None:
            found.water_body_id = body.id

        self.stations[code] = found
        return found


def ensure_source(db: Session, provider: WaterDataProvider) -> DataSource:
    """Get or create the ``data_sources`` row describing a provider."""
    info = provider.info
    source = db.scalar(select(DataSource).where(DataSource.key == info.key))
    if source is None:
        source = DataSource(key=info.key)
        db.add(source)

    source.name = info.name
    source.organisation = info.organisation
    source.url = info.url
    source.dataset = info.dataset
    source.licence = info.licence
    source.expected_cadence = str(info.cadence)
    source.notes = "\n".join(info.notes) if info.notes else None
    db.flush()
    return source


def ingest_provider(
    db: Session,
    provider_key: str = "cpcb_nwdp",
    *,
    states: list[str] | None = None,
    max_plans: int | None = None,
    max_rows_per_plan: int | None = None,
) -> dict:
    """Run one ingestion pass and return its summary.

    Args:
        db: open session; the run commits per plan so a later failure keeps
            the work already done.
        provider_key: registered provider to read from.
        states: restrict to these state codes. ``None`` means every state,
            which is 315 resources and takes a long time -- the API exposes
            the state filter precisely so a run can be scoped.
        max_plans: cap the number of resources fetched, for smoke tests.
        max_rows_per_plan: cap rows per resource, for smoke tests.
    """
    provider = get_provider(provider_key)
    source = ensure_source(db, provider)

    run = IngestionRun(
        run_id=_new_run_id(),
        source_key=provider_key,
        started_at=datetime.now(UTC),
        status="running",
        errors=[],
        warnings=[],
        detail={},
    )
    db.add(run)
    db.commit()

    plans = provider.plans(states=states)
    if max_plans is not None:
        plans = plans[:max_plans]

    registry = _Registry(db, source)
    errors: list[str] = []
    warnings: list[str] = []
    touched_bodies: set[int] = set()
    touched_stations: set[int] = set()
    plans_done = 0

    for plan in plans:
        try:
            counts = _ingest_plan(
                db,
                provider,
                plan,
                registry,
                source,
                touched_bodies,
                touched_stations,
                max_rows=max_rows_per_plan,
            )
        except ProviderUnavailableError as exc:
            # A provider failure is recorded and the run continues with the
            # remaining plans. Losing one state's data must not discard the
            # rest of the run's work.
            message = f"{plan.description}: {exc}"
            errors.append(message)
            logger.error("ingest_plan_failed", extra={"plan": plan.identifier})
            db.rollback()
            continue

        run.records_seen += counts["seen"]
        run.records_valid += counts["valid"]
        run.records_rejected += counts["rejected"]
        run.records_inserted += counts["inserted"]
        run.records_duplicate += counts["duplicate"]
        plans_done += 1
        db.commit()

    _recompute_denormalised(db, touched_bodies, touched_stations)
    _recompute_district_centroids(db)

    run.finished_at = datetime.now(UTC)
    run.stations_created = registry.created_stations
    run.water_bodies_created = registry.created_bodies
    run.errors = errors
    run.warnings = warnings
    run.status = (
        "failed" if errors and plans_done == 0 else ("partial" if errors else "success")
    )
    run.detail = {
        "plans_total": len(plans),
        "plans_completed": plans_done,
        "states": states or "all",
        "provider": provider_key,
    }

    source.last_success_at = run.finished_at if plans_done else source.last_success_at
    source.last_error = errors[0] if errors else None
    source.is_available = bool(plans_done)
    db.commit()

    summary = {
        "run_id": run.run_id,
        "source": provider_key,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "plans_total": len(plans),
        "plans_completed": plans_done,
        "records_seen": run.records_seen,
        "records_valid": run.records_valid,
        "records_rejected": run.records_rejected,
        "records_inserted": run.records_inserted,
        "records_duplicate": run.records_duplicate,
        "stations_created": run.stations_created,
        "water_bodies_created": run.water_bodies_created,
        "errors": errors,
    }
    logger.info("ingest_complete", extra=summary)
    return summary


def _ingest_plan(
    db: Session,
    provider: WaterDataProvider,
    plan: FetchPlan,
    registry: _Registry,
    source: DataSource,
    touched_bodies: set[int],
    touched_stations: set[int],
    *,
    max_rows: int | None,
) -> dict:
    """Fetch, match and persist one resource."""
    rows: list[ObservationRow] = []
    for index, row in enumerate(provider.fetch(plan)):
        if max_rows is not None and index >= max_rows:
            break
        rows.append(row)

    counts = {"seen": len(rows), "valid": 0, "rejected": 0, "inserted": 0, "duplicate": 0}
    if not rows:
        return counts

    # -- MATCH: resolve every distinct station name in this resource -------
    # Two passes, because type propagation needs to see the whole batch
    # before it can tell that "GODAVARI AT NASIK" is a river.
    by_station: dict[str, list[ObservationRow]] = defaultdict(list)
    for row in rows:
        by_station[row.station_name].append(row)

    first_pass = {
        name: resolve(name, river=group[0].river, tributary=group[0].tributary)
        for name, group in by_station.items()
    }
    learned = propagate_types(list(first_pass.values()))
    matches = {
        name: apply_propagation(match, learned) for name, match in first_pass.items()
    }

    retrieved_at = datetime.now(UTC)
    pending: list[WaterQualityObservation] = []

    for name, group in by_station.items():
        sample = group[0]
        state = registry.state(sample.state_name, sample.state_code)
        district = registry.district(state, sample.district)
        body = registry.water_body(
            matches[name], state, district, sample.latitude, sample.longitude
        )
        station = registry.station(sample, body, state, district)
        touched_stations.add(station.id)
        if body is not None:
            touched_bodies.add(body.id)

        # -- DEDUPLICATE: one query per station, not per row ---------------
        existing = {
            (parameter, _as_utc(observed_at))
            for parameter, observed_at in db.execute(
                select(
                    WaterQualityObservation.parameter,
                    WaterQualityObservation.observed_at,
                ).where(WaterQualityObservation.station_id == station.id)
            ).all()
        }
        seen_in_batch: set[tuple[str, datetime | None]] = set()

        for row in group:
            flag, notes = _validate(row)
            if flag is QualityFlag.INVALID:
                counts["rejected"] += 1
            else:
                counts["valid"] += 1

            key = (row.parameter_key, _as_utc(row.observed_at))
            if key in existing or key in seen_in_batch:
                counts["duplicate"] += 1
                continue
            seen_in_batch.add(key)

            pending.append(
                WaterQualityObservation(
                    station_id=station.id,
                    water_body_id=body.id if body else None,
                    source_id=source.id,
                    parameter=row.parameter_key,
                    observed_at=row.observed_at,
                    observed_date=row.observed_at.date(),
                    value=row.value,
                    unit=row.unit,
                    normalized_value=row.normalized_value,
                    normalized_unit=row.normalized_unit,
                    qualitative_value=row.qualitative_value,
                    quality_flag=flag,
                    quality_notes=notes,
                    evidence_type=WaterEvidenceType.MEASURED,
                    source_reference=row.source_reference,
                    retrieved_at=retrieved_at,
                    raw_value=row.raw_value,
                )
            )

    db.add_all(pending)
    db.flush()
    counts["inserted"] = len(pending)
    return counts


def _recompute_denormalised(
    db: Session, body_ids: set[int], station_ids: set[int]
) -> None:
    """Refresh the cached counters the map and list endpoints read.

    These exist so the map can filter and colour thousands of features
    without a correlated subquery per feature. They are recomputed here, at
    the end of ingestion, rather than maintained incrementally -- a counter
    updated in two places is a counter that eventually disagrees with itself.
    """
    for station_id in station_ids:
        latest, count = db.execute(
            select(
                func.max(WaterQualityObservation.observed_at),
                func.count(WaterQualityObservation.id),
            ).where(WaterQualityObservation.station_id == station_id)
        ).one()
        station = db.get(MonitoringStation, station_id)
        if station is not None:
            station.latest_observed_at = latest
            station.observation_count = count or 0

    for body_id in body_ids:
        latest, count = db.execute(
            select(
                func.max(WaterQualityObservation.observed_at),
                func.count(WaterQualityObservation.id),
            ).where(WaterQualityObservation.water_body_id == body_id)
        ).one()
        stations = db.scalars(
            select(MonitoringStation).where(MonitoringStation.water_body_id == body_id)
        ).all()

        body = db.get(WaterBody, body_id)
        if body is None:
            continue
        body.latest_observed_at = latest
        body.observation_count = count or 0
        body.station_count = len(stations)

        located = [
            s for s in stations if s.latitude is not None and s.longitude is not None
        ]
        if located:
            body.centroid_lat = sum(s.latitude for s in located) / len(located)
            body.centroid_lon = sum(s.longitude for s in located) / len(located)

    db.commit()


def _recompute_district_centroids(db: Session) -> None:
    """Derive a district centroid from its stations.

    Derived, and labelled as such in the model: the source publishes no
    district boundary, so this is the mean of observed stations rather than a
    geographic centroid. It is good enough to fly the map to a district and
    honest about what it is.
    """
    rows = db.execute(
        select(
            MonitoringStation.district_id,
            func.avg(MonitoringStation.latitude),
            func.avg(MonitoringStation.longitude),
        )
        .where(
            MonitoringStation.district_id.is_not(None),
            MonitoringStation.latitude.is_not(None),
            MonitoringStation.geo_quality == "ok",
        )
        .group_by(MonitoringStation.district_id)
    ).all()

    for district_id, lat, lon in rows:
        district = db.get(District, district_id)
        if district is not None:
            district.centroid_lat = lat
            district.centroid_lon = lon
    db.commit()


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Re-exported for the spatial query layer."""
    return haversine_km(lat1, lon1, lat2, lon2)
