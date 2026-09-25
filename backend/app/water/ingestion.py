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
from app.models.enums import QualityFlag, WaterBodyType, WaterEvidenceType
from app.models.water import (
    DataSource,
    District,
    IngestionRun,
    MonitoringStation,
    RiverStretch,
    SourceResourceState,
    State,
    WaterBody,
    WaterBodyStatusHistory,
    WaterEvidence,
    WaterQualityObservation,
)
from app.water.matching import (
    DRAIN_TO_RIVER_KM,
    RIVER_LINK_KM,
    MatchResult,
    apply_propagation,
    canonical_core,
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
            slug = slugify(label)
            # Two codes can arrive with the same name (merged UTs); the code is
            # the identity, so the second one gets a code-qualified slug.
            if self.db.scalar(select(State.id).where(State.slug == slug)):
                slug = f"{slug}-{key.lower()}"
            found = State(code=key, name=label, slug=slug)
            self.db.add(found)
            self.db.flush()
        self.states[key] = found
        return found

    def reset(self) -> None:
        """Forget cached rows after a rollback, so none is reused detached."""
        self.states.clear()
        self.districts.clear()
        self.bodies.clear()
        self.stations.clear()

    def district(self, state: State | None, name: str | None) -> District | None:
        """Get or create a district within a state."""
        if state is None or not name:
            return None
        # The source mixes "Mumbai Suburban" with "MUMBAI CITY". Only
        # all-caps names are recased, so a deliberate spelling is never touched.
        if name.isupper():
            name = name.title()
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

        if found is None and match.method == "unclassified":
            # An untyped name that an earlier run already typed ("YAMUNA AT X"
            # once "YAMUNA RIVER" is known) attaches to that body directly,
            # instead of creating a duplicate for the reconcile pass to undo.
            for typed in self.db.scalars(
                select(WaterBody).where(
                    WaterBody.normalized_name == match.normalized_name,
                    WaterBody.water_type != WaterBodyType.OTHER,
                )
            ):
                if is_plausible_merge(
                    latitude, longitude, typed.centroid_lat, typed.centroid_lon
                ):
                    found = typed
                    break

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
            aliases=list(match.aliases),
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
        position: str | None = None,
    ) -> MonitoringStation:
        """Get or create the monitoring station a row came from."""
        # Scoped by state: the same label ("RANI TALAB") names different
        # stations in different states, and keying on the label alone merged
        # them into one station with two states' observations.
        code = f"{(row.state_code or '').upper()}:{normalise_name(row.station_name)}"[
            :160
        ]
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
                position_descriptor=(position or None) and position[:300],
            )
            self.db.add(found)
            self.db.flush()
            self.created_stations += 1
        else:
            if found.water_body_id is None and body is not None:
                found.water_body_id = body.id
            if found.position_descriptor is None and position:
                found.position_descriptor = position[:300]

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
    source.source_type = info.source_type
    source.observation_method = info.observation_method
    source.reliability_note = info.reliability_note
    db.flush()
    return source


def ingest_provider(
    db: Session,
    provider_key: str = "cpcb_nwdp",
    *,
    states: list[str] | None = None,
    max_plans: int | None = None,
    max_rows_per_plan: int | None = None,
    incremental: bool = True,
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
        incremental: skip resources whose row count is unchanged since the
            last successful ingest. Pass False to re-read everything.
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

    skipped = 0
    for plan in plans:
        state = _resource_state(db, provider_key, plan)
        if incremental and _unchanged(provider, plan, state):
            skipped += 1
            continue
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
            registry.reset()
            continue
        except Exception as exc:
            # A data problem inside one resource (a constraint the source's
            # rows violate) is recorded against that resource, rolled back,
            # and the run moves on. Before this, one conflicting row in the
            # Dadra & Nagar Haveli resource aborted a 35-state run.
            errors.append(
                f"{plan.description}: ingestion error: {type(exc).__name__}: {exc}"[:500]
            )
            logger.exception("ingest_plan_error", extra={"plan": plan.identifier})
            db.rollback()
            registry.reset()
            continue

        _record_resource_state(db, state, counts)
        run.records_seen += counts["seen"]
        run.records_valid += counts["valid"]
        run.records_rejected += counts["rejected"]
        run.records_inserted += counts["inserted"]
        run.records_duplicate += counts["duplicate"]
        plans_done += 1
        db.commit()

    reconciled = _reconcile_untyped(db)
    touched_bodies |= reconciled["touched"]
    touched_bodies -= reconciled["deleted"]
    linked = link_river_fragments(db)
    touched_bodies |= linked["touched"]
    touched_bodies -= linked["deleted"]
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
        "bodies_merged": reconciled["merged"],
        "bodies_retyped": reconciled["retyped"],
        "river_fragments_linked": linked["merged"],
        "plans_total": len(plans),
        "plans_completed": plans_done,
        "plans_skipped_unchanged": skipped,
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


def _resource_state(db: Session, source_key: str, plan: FetchPlan) -> SourceResourceState:
    """The stored sync state for one resource, created if absent."""
    state = db.scalar(
        select(SourceResourceState).where(
            SourceResourceState.source_key == source_key,
            SourceResourceState.resource_id == plan.identifier,
        )
    )
    if state is None:
        state = SourceResourceState(
            source_key=source_key,
            resource_id=plan.identifier,
            description=plan.description,
        )
        db.add(state)
        db.flush()
    state.description = plan.description
    return state


def _unchanged(
    provider: WaterDataProvider, plan: FetchPlan, state: SourceResourceState
) -> bool:
    """Whether the source still reports exactly what was last ingested."""
    if state.last_ingested_at is None or state.last_total is None:
        return False
    total = provider.resource_total(plan)
    if total is None:
        return False
    if total != state.last_total:
        return False
    logger.info(
        "resource_unchanged",
        extra={"resource": plan.identifier, "rows": total},
    )
    return True


def _record_resource_state(db: Session, state: SourceResourceState, counts: dict) -> None:
    """Store what this resource yielded, for the next incremental run."""
    state.last_total = counts.get("seen", 0) or state.last_total
    state.records_ingested = counts.get("inserted", 0)
    state.last_ingested_at = datetime.now(UTC)
    state.last_observation_at = counts.get("max_observed_at") or state.last_observation_at
    state.last_status = "ok"
    state.last_error = None


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

    counts: dict = {
        "seen": len(rows),
        "valid": 0,
        "rejected": 0,
        "inserted": 0,
        "duplicate": 0,
        "max_observed_at": max((r.observed_at for r in rows), default=None),
    }
    if not rows:
        return counts

    # -- MATCH: resolve every distinct station name in this resource -------
    # Two passes, because type propagation needs to see the whole batch
    # before it can tell that "GODAVARI AT NASIK" is a river.
    # Grouped by (state, label): the same label names different stations in
    # different states, and grouping on the label alone folded them together.
    by_station: dict[tuple[str, str], list[ObservationRow]] = defaultdict(list)
    for row in rows:
        by_station[((row.state_code or "").upper(), row.station_name)].append(row)

    first_pass = {
        key: resolve(key[1], river=group[0].river, tributary=group[0].tributary)
        for key, group in by_station.items()
    }
    learned = propagate_types(list(first_pass.values()))
    matches = {
        key: apply_propagation(match, learned) for key, match in first_pass.items()
    }

    retrieved_at = datetime.now(UTC)
    pending: list[WaterQualityObservation] = []
    seen_by_station: dict[int, set[tuple[str, datetime | None]]] = {}

    for name, group in by_station.items():
        sample = group[0]
        state = registry.state(sample.state_name, sample.state_code)
        district = registry.district(state, sample.district)
        body = registry.water_body(
            matches[name], state, district, sample.latitude, sample.longitude
        )
        match = matches[name]
        station = registry.station(sample, body, state, district, match.position)
        if body is not None and match.aliases:
            known = list(body.aliases or [])
            added = [a for a in match.aliases if a not in known and a != body.name]
            if added:
                body.aliases = known + added
        touched_stations.add(station.id)
        if body is not None:
            touched_bodies.add(body.id)

        # -- DEDUPLICATE: one query per station, not per row ---------------
        # Keyed by station for the whole plan, not per group: two labels in
        # one resource can normalise to the same station, and inserts are only
        # flushed at the end, so a per-group set never saw the other group's
        # pending rows and the database rejected the batch.
        if station.id not in seen_by_station:
            seen_by_station[station.id] = {
                (parameter, _as_utc(observed_at))
                for parameter, observed_at in db.execute(
                    select(
                        WaterQualityObservation.parameter,
                        WaterQualityObservation.observed_at,
                    ).where(WaterQualityObservation.station_id == station.id)
                ).all()
            }
        seen = seen_by_station[station.id]

        for row in group:
            flag, notes = _validate(row)
            if flag is QualityFlag.INVALID:
                counts["rejected"] += 1
            else:
                counts["valid"] += 1

            key = (row.parameter_key, _as_utc(row.observed_at))
            if key in seen:
                counts["duplicate"] += 1
                continue
            seen.add(key)

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


def _merge_into(db: Session, source: WaterBody, target: WaterBody) -> None:
    """Move everything attached to ``source`` onto ``target`` and delete it.

    The source's name is kept as an alias of the target, so a search for the
    old label still finds the merged water body.
    """
    from app.models.water_geo import SourceClassification, WaterBodyGeometry, WaterImage

    for model in (
        MonitoringStation,
        WaterQualityObservation,
        WaterEvidence,
        RiverStretch,
        SourceClassification,
        WaterImage,
    ):
        db.query(model).filter(model.water_body_id == source.id).update(
            {model.water_body_id: target.id}, synchronize_session=False
        )
    # A geometry matched to either fragment describes only part of the merged
    # body; both are dropped so the next geometry pass matches the whole.
    db.query(WaterBodyGeometry).filter(
        WaterBodyGeometry.water_body_id.in_([source.id, target.id])
    ).delete(synchronize_session=False)
    target.geometry_status = "not_attempted"
    db.query(WaterBodyStatusHistory).filter(
        WaterBodyStatusHistory.water_body_id == source.id
    ).delete(synchronize_session=False)
    aliases = list(target.aliases or [])
    for name in [source.name, *(source.aliases or [])]:
        if name not in aliases and name != target.name:
            aliases.append(name)
    target.aliases = aliases
    db.delete(source)


def _reconcile_untyped(db: Session) -> dict:
    """Resolve untyped water bodies against the whole corpus.

    Type propagation inside a single resource cannot see across resources:
    Delhi's ``YAMUNA AT <place>`` stations never meet Uttar Pradesh's
    ``YAMUNA RIVER <place>``, so the same river ended up as two water bodies,
    one of them untyped. This pass runs after every plan, over everything
    stored, and for each untyped body whose name matches a body typed by an
    explicit keyword:

    * if a same-named typed body is geographically plausible, the untyped
      body's stations and observations are moved onto it and the untyped
      record is deleted -- one river, one record;
    * otherwise its type is upgraded in place, marked ``type_propagated``
      with the lower confidence that method carries.

    Names claimed by conflicting types are left alone rather than resolved by
    vote, exactly as in the per-resource pass.
    """
    typed: dict[str, list[WaterBody]] = defaultdict(list)
    for body in db.scalars(
        select(WaterBody).where(
            WaterBody.match_method.in_(("station_name_parse", "source_field")),
            WaterBody.water_type != WaterBodyType.OTHER,
        )
    ):
        typed[body.normalized_name].append(body)

    merged = retyped = 0
    touched: set[int] = set()
    deleted: set[int] = set()

    untyped = db.scalars(
        select(WaterBody).where(WaterBody.match_method == "unclassified")
    ).all()

    for body in untyped:
        candidates = typed.get(body.normalized_name) or []
        types = {str(c.water_type) for c in candidates}
        if len(types) != 1:
            continue

        plausible = [
            c
            for c in candidates
            if is_plausible_merge(
                body.centroid_lat, body.centroid_lon, c.centroid_lat, c.centroid_lon
            )
        ]
        if plausible:
            target = min(
                plausible,
                key=lambda c: (
                    haversine_km(
                        body.centroid_lat,
                        body.centroid_lon,
                        c.centroid_lat,
                        c.centroid_lon,
                    )
                    if None
                    not in (
                        body.centroid_lat,
                        body.centroid_lon,
                        c.centroid_lat,
                        c.centroid_lon,
                    )
                    else 0.0
                ),
            )
            _merge_into(db, body, target)
            touched.add(target.id)
            deleted.add(body.id)
            merged += 1
        else:
            learned = {body.normalized_name: candidates[0].water_type}
            upgraded = apply_propagation(
                MatchResult(
                    name=body.name,
                    normalized_name=body.normalized_name,
                    water_type=WaterBodyType.OTHER,
                    method="unclassified",
                    confidence=body.match_confidence,
                ),
                learned,
            )
            body.water_type = upgraded.water_type
            body.name = upgraded.name
            body.match_method = upgraded.method
            body.match_confidence = upgraded.confidence
            touched.add(body.id)
            retyped += 1

    # -- Drains sharing a river's name ------------------------------------
    # "MITHI NALLAH AT KURLA" and "MITHI RIVER MAHIM" are one watercourse
    # under a local label. A drain merges into a same-named river only when
    # the two are within DRAIN_TO_RIVER_KM; further apart they stay separate.
    rivers: dict[str, list[WaterBody]] = defaultdict(list)
    for body in db.scalars(
        select(WaterBody).where(WaterBody.water_type == WaterBodyType.RIVER)
    ):
        rivers[body.normalized_name].append(body)
    for drain in db.scalars(
        select(WaterBody).where(WaterBody.water_type == WaterBodyType.DRAIN)
    ).all():
        if drain.id in deleted:
            continue
        for river in rivers.get(drain.normalized_name, []):
            if None in (
                drain.centroid_lat,
                drain.centroid_lon,
                river.centroid_lat,
                river.centroid_lon,
            ):
                continue
            km = haversine_km(
                drain.centroid_lat,
                drain.centroid_lon,
                river.centroid_lat,
                river.centroid_lon,
            )
            if km <= DRAIN_TO_RIVER_KM:
                _merge_into(db, drain, river)
                touched.add(river.id)
                deleted.add(drain.id)
                merged += 1
                break

    db.commit()
    if merged or retyped:
        logger.info(
            "water_bodies_reconciled", extra={"merged": merged, "retyped": retyped}
        )
    return {"merged": merged, "retyped": retyped, "touched": touched, "deleted": deleted}


def _plain_name(name: str) -> str:
    """A body's name without the "(State)" qualifier added to split it."""
    return name.split(" (")[0].strip()


def _find(parent: dict[int, int], i: int) -> int:
    """Union-find root with path halving."""
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _name_river_group(db: Session, targets: list[WaterBody]) -> None:
    """Give the main river the plain name and qualify the others by state.

    Slugs are left alone: they are identifiers that pages and answers link
    to, and so is ``normalized_name``, which is the identity key every match
    is made against: rewriting it from the display name turned the key
    "AMRAVATI" into "AMRAVATI RIVER" and broke later matching.
    """
    if not targets:
        return
    plain = _plain_name(targets[0].name)
    # Best-sampled wins; on a tie the body that already carries the plain
    # name keeps it, so nothing is renamed for no reason.
    primary = max(targets, key=lambda b: (b.station_count or 0, b.name == plain))
    for body in targets:
        if body is primary:
            wanted = plain
        elif body.name == plain:
            state = db.get(State, body.state_id) if body.state_id else None
            wanted = f"{plain} ({state.name if state else 'Unknown'})"
        else:
            continue
        if body.name != wanted:
            aliases = list(body.aliases or [])
            if body.name not in aliases:
                aliases.append(body.name)
            body.aliases = aliases
            body.name = wanted


def link_river_fragments(db: Session) -> dict:
    """Join same-named river bodies that are one connected river.

    Ingestion splits a same-named river when a station is more than
    ``MAX_MERGE_KM`` from the body's *centroid*. For a river that is the wrong
    test: the Ganga's centroid sits in whichever state was ingested first, so
    Uttar Pradesh's stations, 100 km from Bihar's nearest one, still landed
    in a separate "(Uttar Pradesh)" body. Here fragments are joined when their
    *nearest stations* are within :data:`RIVER_LINK_KM`, transitively, which
    follows the river rather than an average point. Fragments with no
    station close to another stay separate: that is what keeps the Amravati
    in Tamil Nadu apart from the Amravati in Gujarat.
    """
    groups: dict[tuple[str, str], list[WaterBody]] = defaultdict(list)
    # Linear features only. Untyped bodies are left alone: their names are
    # often generic ("Pond", "STP") and a distance rule would join unrelated
    # places.
    for body in db.scalars(
        select(WaterBody).where(
            WaterBody.water_type.in_([WaterBodyType.RIVER, WaterBodyType.CANAL])
        )
    ):
        # Canonical spelling, so "Satluj" and "Sutlej" fall in one group.
        key = canonical_core(normalise_name(_plain_name(body.name)))
        groups[(str(body.water_type), key)].append(body)

    merged = 0
    touched: set[int] = set()
    deleted: set[int] = set()
    for bodies in groups.values():
        if len(bodies) < 2:
            continue
        points: dict[int, list[tuple[float, float]]] = {}
        for body in bodies:
            points[body.id] = [
                (lat, lon)
                for lat, lon in db.execute(
                    select(MonitoringStation.latitude, MonitoringStation.longitude).where(
                        MonitoringStation.water_body_id == body.id,
                        MonitoringStation.latitude.is_not(None),
                    )
                )
            ]
        parent = {b.id: b.id for b in bodies}
        for i, a in enumerate(bodies):
            for b in bodies[i + 1 :]:
                if (
                    _find(parent, a.id) == _find(parent, b.id)
                    or not points[a.id]
                    or not points[b.id]
                ):
                    continue
                nearest = min(
                    distance_km(p[0], p[1], q[0], q[1])
                    for p in points[a.id]
                    for q in points[b.id]
                )
                if nearest <= RIVER_LINK_KM:
                    parent[_find(parent, b.id)] = _find(parent, a.id)

        components: dict[int, list[WaterBody]] = defaultdict(list)
        for body in bodies:
            components[_find(parent, body.id)].append(body)
        targets: list[WaterBody] = []
        for members in components.values():
            # Prefer the body already carrying the plain name (its slug is
            # the one people link to), else the best-sampled fragment.
            target = max(
                members,
                key=lambda b: (b.name == _plain_name(b.name), b.station_count or 0),
            )
            for other in members:
                if other.id == target.id:
                    continue
                target.station_count = (target.station_count or 0) + (
                    other.station_count or 0
                )
                _merge_into(db, other, target)
                deleted.add(other.id)
                merged += 1
                touched.add(target.id)
            targets.append(target)
        _name_river_group(db, targets)
    db.commit()
    if merged:
        logger.info("river_fragments_linked", extra={"merged": merged})
    return {"merged": merged, "touched": touched, "deleted": deleted}


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
