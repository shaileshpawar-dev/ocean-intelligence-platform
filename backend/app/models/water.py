"""India Water Intelligence ORM models.

The central entity here is the **water body**, not the pollution event. That
inversion is the point of the V2 data model: a pollution event is something
that may or may not have happened to a water body, whereas the water body
exists, has a location, has a monitoring history, and remains a meaningful
thing to look up even when nothing has been measured for years.

Geometry is stored as plain latitude/longitude columns rather than PostGIS
types. The reason is deliberate and documented in docs/DATA_MODEL.md: the
platform must keep running on SQLite for local development and for the
current container deployment, and a PostGIS-typed column makes that
impossible. Bounding-box and radius queries are implemented in SQL over these
columns, which is exact for the box case and accurate enough for the radius
case at the scale of Indian districts. The migration path to real geometry is
a column addition, not a rewrite.
"""

from __future__ import annotations

from datetime import datetime

# SQLite has no native JSON column type, but SQLAlchemy's JSON type works on
# both SQLite and Postgres, so alias lists and raw payloads stay portable.
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    QualityFlag,
    WaterBodyType,
    WaterEvidenceType,
    WaterStatus,
)


class DataSource(Base, TimestampMixin):
    """An upstream provider of water data.

    Every observation points at one of these, so "where did this number come
    from?" is answerable by a join rather than by guesswork.
    """

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """Stable machine key, e.g. ``cpcb_nwdp``."""

    name: Mapped[str] = mapped_column(String(200))
    organisation: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dataset: Mapped[str | None] = mapped_column(String(300), nullable=True)
    licence: Mapped[str | None] = mapped_column(String(200), nullable=True)

    expected_cadence: Mapped[str] = mapped_column(String(32), default="unknown")
    """Declared publishing frequency. Drives freshness judgement."""

    # -- What kind of source this is ---------------------------------------
    # Recorded as facts, not as a ranking. Two agencies measuring the same
    # river are not "better" and "worse"; they sample on different schedules,
    # by different methods, and the reader is told which is which.
    source_type: Mapped[str] = mapped_column(String(32), default="government")
    """``government``, ``state_board``, ``research``, ``satellite``, ``other``."""

    observation_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """How the numbers are produced, e.g. ``manual_grab_sample``,
    ``continuous_sensor``, ``satellite_derived``."""

    reliability_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What is known about the source's reliability, in words, with its
    basis. Never a score."""

    dataset_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """Version or edition the last sync read, where the source declares one."""

    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """The newest observation this source has supplied. Answers "is there
    anything newer?" without scanning the observation table."""

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceResourceState(Base, TimestampMixin):
    """What was last ingested from one resource of one source.

    Exists so a re-run is cheap. The portal reports a row count per resource
    for the price of one request; when it has not changed since the last
    successful ingest, that resource is skipped instead of being paged in
    full. Re-importing 582,192 observations to discover that nothing moved is
    what this avoids.
    """

    __tablename__ = "source_resource_state"
    __table_args__ = (
        UniqueConstraint("source_key", "resource_id", name="uq_source_resource"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    last_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Row count the source reported at the last successful ingest."""

    last_ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    dataset_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_status: Mapped[str] = mapped_column(String(24), default="ok")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class State(Base, TimestampMixin):
    """An Indian state or union territory."""

    __tablename__ = "states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(4), unique=True, index=True)
    """Two-letter code used by the source filenames, e.g. ``MH``."""

    name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lgd_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    """Local Government Directory code, as published by the source."""

    districts: Mapped[list[District]] = relationship(back_populates="state")


class District(Base, TimestampMixin):
    """A district within a state.

    Doubles as the platform's "city" unit. Indian monitoring data is keyed to
    districts, and the places users search for -- Mumbai, Pune, Bengaluru --
    are districts in that data. Inventing a separate city table would mean
    inventing city boundaries the source never supplied.
    """

    __tablename__ = "districts"
    __table_args__ = (
        UniqueConstraint("state_id", "slug", name="uq_district_state_slug"),
        Index("ix_district_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("states.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(160), index=True)
    lgd_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    centroid_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Mean of the district's monitoring stations. Derived, not authoritative;
    the source publishes no district boundary."""

    state: Mapped[State] = relationship(back_populates="districts")


class WaterBody(Base, TimestampMixin):
    """A river, lake, pond, reservoir, creek or coastal location.

    The canonical entity. Identity is resolved by
    :mod:`app.water.matching` from station names and source fields, because
    the CPCB extracts publish an empty ``River`` column and carry the water
    body's name inside the station name instead.
    """

    __tablename__ = "water_bodies"
    __table_args__ = (
        Index("ix_water_body_geo", "centroid_lat", "centroid_lon"),
        Index("ix_water_body_type_state", "water_type", "state_id"),
        Index("ix_water_body_latest", "latest_observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(220), index=True)

    normalized_name: Mapped[str] = mapped_column(String(220), index=True)
    """Upper-cased, de-punctuated, suffix-stripped form used for matching."""

    water_type: Mapped[WaterBodyType] = mapped_column(String(32), index=True)

    state_id: Mapped[int | None] = mapped_column(
        ForeignKey("states.id"), nullable=True, index=True
    )
    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id"), nullable=True, index=True
    )

    basin: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sub_basin: Mapped[str | None] = mapped_column(String(160), nullable=True)

    centroid_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Mean position of the body's stations. Not a surveyed centroid."""

    aliases: Mapped[list] = mapped_column(JSON, default=list)
    """Other names seen in source data, kept so search can match them."""

    match_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    """How confident the matcher is that the stations grouped here are one
    water body. Below 1.0 means the name was parsed, not supplied."""

    match_method: Mapped[str] = mapped_column(String(48), default="source_field")
    """``source_field``, ``station_name_parse`` or ``manual_override``."""

    source_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    """Identifiers of this water body in external sources, e.g.
    ``{"osm": ["way/49011690", ...]}``. Empty until a source supplies one."""

    designated_use: Mapped[str | None] = mapped_column(String(8), nullable=True)
    """CPCB designated-best-use class *if an authoritative source states it*.
    Never inferred; null for every water body today."""

    designated_use_source: Mapped[str | None] = mapped_column(String(300), nullable=True)

    geometry_status: Mapped[str] = mapped_column(String(24), default="not_attempted")
    """``not_attempted``, ``matched``, ``ambiguous``, ``not_found``,
    ``unsupported`` or ``error`` -- so "no geometry" is always explained."""

    # -- Denormalised for map and list performance -------------------------
    # Recomputed by the ingestion pipeline. Kept on the row so the map
    # endpoint can filter and colour thousands of features without a
    # correlated subquery per feature.
    latest_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    station_count: Mapped[int] = mapped_column(Integer, default=0)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    cached_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """Last computed present-tense :class:`WaterStatus`. Advisory; the detail
    endpoint always recomputes from observations so a stale cache cannot
    mislead."""

    cached_historical_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    """Status as at the date of the latest observation.

    Kept because the present-tense band collapses to NO_RECENT_DATA for every
    water body whose source has not published lately, which is true but would
    render the map a uniform grey and hide real, dated findings. This field is
    only ever displayed with that date attached."""

    state: Mapped[State | None] = relationship()
    district: Mapped[District | None] = relationship()
    stations: Mapped[list[MonitoringStation]] = relationship(back_populates="water_body")


class RiverStretch(Base, TimestampMixin):
    """A named segment of a river.

    Only created where the evidence supports it: CPCB's criterion is two or
    more polluted monitoring locations in continuous sequence on the same
    river. Stretches are never invented to subdivide a river that has one
    station.
    """

    __tablename__ = "river_stretches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    water_body_id: Mapped[int] = mapped_column(ForeignKey("water_bodies.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))

    priority_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    """CPCB restoration priority I-V as published for this stretch."""

    max_bod: Mapped[float | None] = mapped_column(Float, nullable=True)
    station_count: Mapped[int] = mapped_column(Integer, default=0)
    derivation: Mapped[str] = mapped_column(String(64), default="source_defined")
    """How the stretch was defined. Only ``source_defined`` is created today:
    the platform does not derive stretches itself."""

    official_stretch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assessment_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)

    water_body: Mapped[WaterBody] = relationship()


class MonitoringStation(Base, TimestampMixin):
    """A physical sampling location."""

    __tablename__ = "monitoring_stations"
    __table_args__ = (
        Index("ix_station_geo", "latitude", "longitude"),
        Index("ix_station_state_district", "state_id", "district_id"),
        UniqueConstraint("source_id", "station_code", name="uq_station_source_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_code: Mapped[str] = mapped_column(String(160), index=True)
    """Stable identifier derived from the source's station name."""

    name: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(300), index=True)

    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    water_body_id: Mapped[int | None] = mapped_column(
        ForeignKey("water_bodies.id"), nullable=True, index=True
    )
    state_id: Mapped[int | None] = mapped_column(ForeignKey("states.id"), nullable=True)
    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id"), nullable=True
    )

    agency: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tehsil: Mapped[str | None] = mapped_column(String(160), nullable=True)
    village: Mapped[str | None] = mapped_column(String(160), nullable=True)

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_descriptor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    """Where on the water body this station samples ("At Nasik D/S ..."),
    parsed from the station name. Kept here so it never splits a body."""

    relationship_type: Mapped[str] = mapped_column(String(32), default="name_match")
    """How the station is tied to its water body: ``name_match``,
    ``on_feature``, ``near_feature``, ``distant_from_feature`` or
    ``unassigned``."""

    geometry_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Distance to the water body's mapped geometry, once geometry exists."""

    geo_quality: Mapped[str] = mapped_column(String(24), default="ok")
    """``ok``, ``suspect`` (outside India's bounding box) or ``missing``."""

    latest_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observation_count: Mapped[int] = mapped_column(Integer, default=0)

    water_body: Mapped[WaterBody | None] = relationship(back_populates="stations")
    source: Mapped[DataSource] = relationship()


class WaterQualityObservation(Base, TimestampMixin):
    """One parameter measured at one station at one time.

    Long-format on purpose: one row per parameter rather than one row per
    sampling event with forty nullable columns. Sources publish wildly
    different parameter sets, and a wide table would be mostly NULL and would
    need a migration every time a source adds a column.

    The pair (value, normalized_value) is also deliberate. ``value`` is what
    the source published; ``normalized_value`` is that value in the
    parameter's canonical unit, or NULL when no exact conversion exists.
    Queries and thresholds use the normalised column, so a unit the platform
    cannot convert is excluded from analysis rather than silently compared
    against a limit in a different unit.
    """

    __tablename__ = "water_quality_observations"
    __table_args__ = (
        # The source is part of the key: two agencies sampling the same
        # station, parameter and moment are two observations, and keeping
        # only one would silently drop a source.
        UniqueConstraint(
            "source_id",
            "station_id",
            "parameter",
            "observed_at",
            name="uq_observation_source_station_param_time",
        ),
        Index("ix_obs_body_param_time", "water_body_id", "parameter", "observed_at"),
        Index("ix_obs_param_time", "parameter", "observed_at"),
        Index("ix_obs_station_time", "station_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_stations.id"), index=True
    )
    water_body_id: Mapped[int | None] = mapped_column(
        ForeignKey("water_bodies.id"), nullable=True, index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)

    parameter: Mapped[str] = mapped_column(String(64), index=True)
    """Canonical parameter key from :mod:`app.water.parameters`."""

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    """Date part, for cheap day-level grouping on SQLite."""

    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qualitative_value: Mapped[str | None] = mapped_column(String(64), nullable=True)

    quality_flag: Mapped[QualityFlag] = mapped_column(String(16), default=QualityFlag.OK)
    quality_notes: Mapped[list] = mapped_column(JSON, default=list)

    evidence_type: Mapped[WaterEvidenceType] = mapped_column(
        String(32), default=WaterEvidenceType.MEASURED
    )
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    """Resource-level citation, e.g. the CKAN resource id it was read from."""

    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """When the platform fetched it -- distinct from when it was measured."""

    raw_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """The published cell, verbatim, so a parse can always be re-checked."""

    station: Mapped[MonitoringStation] = relationship()
    source: Mapped[DataSource] = relationship()


class WaterEvidence(Base, TimestampMixin):
    """A non-measurement piece of evidence attached to a water body.

    Satellite proxies, image detections, document claims and model
    inferences all land here, each tagged with the kind of claim it is.
    Measurements do not: they have their own table with units, limits and
    quality flags, and flattening them into free text would lose all of it.
    """

    __tablename__ = "water_evidence"
    __table_args__ = (Index("ix_evidence_body_type", "water_body_id", "evidence_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    water_body_id: Mapped[int | None] = mapped_column(
        ForeignKey("water_bodies.id"), nullable=True, index=True
    )
    station_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitoring_stations.id"), nullable=True
    )

    evidence_type: Mapped[WaterEvidenceType] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)

    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Only set where the producing method defines one. Never invented."""

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id"), nullable=True
    )
    citation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    water_body: Mapped[WaterBody | None] = relationship()


class IngestionRun(Base, TimestampMixin):
    """Audit record for one ingestion execution.

    Counts are kept per run so a silent degradation -- a source that starts
    returning half as many rows -- is visible as history rather than being
    discovered when a user reports a gap.
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="running")

    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_valid: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, default=0)

    stations_created: Mapped[int] = mapped_column(Integer, default=0)
    water_bodies_created: Mapped[int] = mapped_column(Integer, default=0)

    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class WaterBodyStatusHistory(Base, TimestampMixin):
    """Status computed for a water body at a point in time.

    Retained so "has this river improved?" is answerable from the platform's
    own record rather than by recomputing history under today's rules.
    """

    __tablename__ = "water_body_status_history"
    __table_args__ = (Index("ix_status_body_time", "water_body_id", "computed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    water_body_id: Mapped[int] = mapped_column(ForeignKey("water_bodies.id"), index=True)
    status: Mapped[WaterStatus] = mapped_column(String(32))
    designated_use: Mapped[str] = mapped_column(String(4))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    engine_version: Mapped[str] = mapped_column(String(32))
    contributing: Mapped[list] = mapped_column(JSON, default=list)
