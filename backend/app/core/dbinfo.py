"""Which database backend is in use, and whether it can do what is asked.

Phase 3 makes PostgreSQL + PostGIS the production target while keeping SQLite
for local development and tests. Two failure modes are worth naming loudly:

* thinking you are on PostgreSQL when the URL still points at SQLite,
* running on PostgreSQL without PostGIS, which silently loses every spatial
  query to the slower Python fallback, and
* running on PostGIS whose schema has no geometry columns, because the
  geometry columns come from a hand-written migration and a database created
  by ``create_all`` does not have them. That case used to report itself as
  spatial-ready and then fail every spatial query on a missing column.

All three are reported at start-up, and the last two are fatal when the
deployment declares itself production.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Engine, text

from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger

logger = get_logger(__name__)


# The application's geometry columns, all added by migration b1a7c0d2e3f4 and
# its successors. Their presence is what separates "PostGIS is installed" from
# "spatial SQL will work".
EXPECTED_GEOMETRY: tuple[tuple[str, str], ...] = (
    ("water_bodies", "centroid_geom"),
    ("water_body_geometries", "geom"),
    ("monitoring_stations", "geom"),
    ("admin_boundaries", "geom"),
    ("cities", "extent_geom"),
    ("water_images", "footprint_geom"),
)


class SpatialBackendUnavailableError(RuntimeError):
    """PostGIS was required by configuration but cannot be used."""


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """What the application is actually talking to."""

    dialect: str
    server_version: str | None
    postgis_version: str | None
    geometry_columns: int = 0
    """How many of the application's geometry columns the schema has. Zero on
    a PostGIS database whose migrations have not run."""

    @property
    def is_postgres(self) -> bool:
        """Whether the connection is PostgreSQL."""
        return self.dialect == "postgresql"

    @property
    def has_postgis(self) -> bool:
        """Whether the PostGIS extension is installed."""
        return bool(self.postgis_version)

    @property
    def spatial_ready(self) -> bool:
        """Whether spatial SQL can actually be run against this schema."""
        return self.has_postgis and self.geometry_columns >= len(EXPECTED_GEOMETRY)

    @property
    def label(self) -> str:
        """One line for logs, health and the start-up banner."""
        if not self.is_postgres:
            return f"{self.dialect} development mode (no spatial SQL)"
        if not self.has_postgis:
            return f"PostgreSQL {self.server_version} WITHOUT PostGIS"
        if not self.spatial_ready:
            return (
                f"PostgreSQL {self.server_version} + PostGIS {self.postgis_version}, "
                f"but {self.geometry_columns} of {len(EXPECTED_GEOMETRY)} geometry "
                "columns exist (migrations have not run)"
            )
        return f"PostgreSQL {self.server_version} + PostGIS {self.postgis_version}"

    def to_dict(self) -> dict:
        """Serialise for the health endpoint."""
        return {
            "dialect": self.dialect,
            "server_version": self.server_version,
            "postgis_version": self.postgis_version,
            "geometry_columns": self.geometry_columns,
            "spatial_sql": self.spatial_ready,
            "label": self.label,
        }


def _probe(db_engine: Engine) -> BackendInfo:
    dialect = db_engine.dialect.name
    if dialect != "postgresql":
        return BackendInfo(dialect=dialect, server_version=None, postgis_version=None)
    with db_engine.connect() as conn:
        server = conn.execute(text("SHOW server_version")).scalar_one()
        postgis = conn.execute(
            text(
                "SELECT extversion FROM pg_extension WHERE extname = 'postgis'",
            )
        ).scalar_one_or_none()
        columns = 0
        if postgis:
            columns = (
                conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM geometry_columns
                         WHERE (f_table_name, f_geometry_column) IN (
                                   ('water_bodies', 'centroid_geom'),
                                   ('water_body_geometries', 'geom'),
                                   ('monitoring_stations', 'geom'),
                                   ('admin_boundaries', 'geom'),
                                   ('cities', 'extent_geom'),
                                   ('water_images', 'footprint_geom')
                               )
                        """
                    )
                ).scalar_one()
                or 0
            )
    return BackendInfo(
        dialect=dialect,
        server_version=str(server),
        postgis_version=postgis,
        geometry_columns=int(columns),
    )


@lru_cache(maxsize=8)
def backend_for(db_engine: Engine) -> BackendInfo:
    """Probe one engine once. Cached, because it is asked per request."""
    try:
        return _probe(db_engine)
    except Exception as exc:  # reported, never fatal here
        logger.warning("database_probe_failed", extra={"error": str(exc)})
        return BackendInfo(
            dialect=db_engine.dialect.name, server_version=None, postgis_version=None
        )


def backend_info() -> BackendInfo:
    """Probe the application's own database."""
    return backend_for(engine)


def spatial_sql_available(db_engine: Engine | None = None) -> bool:
    """Whether queries on this engine may use PostGIS functions.

    Requires both the extension and the geometry columns: with the extension
    alone, every spatial query fails on a column that is not there, which is
    worse than using the Python fallback.
    """
    return backend_for(db_engine or engine).spatial_ready


def report_backend() -> BackendInfo:
    """Log the backend and refuse a production start without PostGIS."""
    info = backend_info()
    logger.info("database_backend", extra=info.to_dict())
    if settings.environment == "production":
        if not info.is_postgres:
            raise SpatialBackendUnavailableError(
                "ENVIRONMENT=production requires PostgreSQL; DATABASE_URL points at "
                f"{info.dialect}. Set DATABASE_URL to the PostgreSQL instance."
            )
        if not info.has_postgis:
            raise SpatialBackendUnavailableError(
                "PostGIS is not installed in the target database. Run "
                "'CREATE EXTENSION postgis;' (the migrations do this) before "
                "starting in production."
            )
        if not info.spatial_ready:
            raise SpatialBackendUnavailableError(
                "PostGIS is installed but the schema has "
                f"{info.geometry_columns} of {len(EXPECTED_GEOMETRY)} geometry "
                "columns: the migrations have not been run against this "
                "database. Run 'python -m app.water.cli db upgrade' (the "
                "migrate job) before starting in production. A schema created "
                "by create_all does not carry the geometry columns."
            )
    return info
