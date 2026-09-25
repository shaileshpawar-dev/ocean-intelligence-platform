"""Which database backend is in use, and whether it can do what is asked.

Phase 3 makes PostgreSQL + PostGIS the production target while keeping SQLite
for local development and tests. Two failure modes are worth naming loudly:

* thinking you are on PostgreSQL when the URL still points at SQLite, and
* running on PostgreSQL without PostGIS, which silently loses every spatial
  query to the slower Python fallback.

Both are reported at start-up, and the second is fatal when the deployment
declares itself production.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Engine, text

from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger

logger = get_logger(__name__)


class SpatialBackendUnavailableError(RuntimeError):
    """PostGIS was required by configuration but is not installed."""


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """What the application is actually talking to."""

    dialect: str
    server_version: str | None
    postgis_version: str | None

    @property
    def is_postgres(self) -> bool:
        """Whether the connection is PostgreSQL."""
        return self.dialect == "postgresql"

    @property
    def has_postgis(self) -> bool:
        """Whether spatial SQL can be used."""
        return bool(self.postgis_version)

    @property
    def label(self) -> str:
        """One line for logs, health and the start-up banner."""
        if not self.is_postgres:
            return f"{self.dialect} development mode (no spatial SQL)"
        if self.has_postgis:
            return f"PostgreSQL {self.server_version} + PostGIS {self.postgis_version}"
        return f"PostgreSQL {self.server_version} WITHOUT PostGIS"

    def to_dict(self) -> dict:
        """Serialise for the health endpoint."""
        return {
            "dialect": self.dialect,
            "server_version": self.server_version,
            "postgis_version": self.postgis_version,
            "spatial_sql": self.has_postgis,
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
    return BackendInfo(
        dialect=dialect, server_version=str(server), postgis_version=postgis
    )


@lru_cache(maxsize=1)
def backend_info() -> BackendInfo:
    """Probe the database once per process."""
    try:
        return _probe(engine)
    except Exception as exc:  # reported, never fatal here
        logger.warning("database_probe_failed", extra={"error": str(exc)})
        return BackendInfo(
            dialect=engine.dialect.name, server_version=None, postgis_version=None
        )


def spatial_sql_available() -> bool:
    """Whether queries may use PostGIS functions."""
    return backend_info().has_postgis


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
    return info
