"""Database engine, session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
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

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    from app.models import Base

    Base.metadata.create_all(bind=engine)
