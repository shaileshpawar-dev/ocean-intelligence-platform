"""Database engine, session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # SQLite plus the FastAPI threadpool needs this; Postgres does not.
    _connect_args = {"check_same_thread": False}
    _path = settings.database_url.replace("sqlite:///", "")
    if _path and _path != ":memory:":
        # Creating the directory can legitimately fail -- an unwritable path in
        # a container, a read-only mount. Failing here kills the process during
        # module import, which surfaces as an unreadable traceback and a
        # crash-looping task. Defer the failure to connection time, where the
        # error names the actual path and the app can still report health.
        try:
            Path(_path).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error(
                "database_directory_unavailable",
                extra={"path": str(Path(_path).parent), "error": str(exc)},
            )

# SQLite has no server to pool against, and passing pool arguments to its
# default pool raises. Everything else gets an explicitly sized pool rather
# than SQLAlchemy's default of 5 + 10 with no recycling.
_pool_args: dict = {}
if not settings.database_url.startswith("sqlite"):
    _pool_args = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    }

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    connect_args=_connect_args,
    # Check the connection is alive before handing it out: an RDS failover or
    # an idle-timeout drop otherwise surfaces as a failed request.
    pool_pre_ping=True,
    **_pool_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Ensure SQLite enforces foreign key constraints during local testing."""
    if engine.url.get_backend_name() == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SchemaNotMigratedError(RuntimeError):
    """The server database has no schema, and start-up must not invent one."""


def init_db() -> None:
    """Make sure a usable schema exists, the right way for this backend.

    On SQLite -- development and tests -- the models are the schema, so the
    tables are created here and the whole thing is disposable.

    On a server database the schema belongs to Alembic. ``create_all`` is not
    called at all: it cannot create the PostGIS geometry columns, which are
    added by hand-written migrations, so it would produce a schema that looks
    complete and has no spatial support. Start-up only checks that the
    migrations have run and says plainly what to do if they have not.
    """
    from app.models import Base

    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(bind=engine)
        return

    if not inspect(engine).has_table("alembic_version"):
        message = (
            f"{engine.url.get_backend_name()} database has no alembic_version "
            "table: the migrations have not been run against it. Run "
            "'python -m app.water.cli db upgrade' (the migrate job) before "
            "starting the application. The schema is deliberately not created "
            "here, because create_all cannot create the PostGIS columns."
        )
        if settings.environment == "production":
            raise SchemaNotMigratedError(message)
        logger.warning("schema_not_migrated", extra={"detail": message})
