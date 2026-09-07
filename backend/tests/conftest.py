"""Shared pytest fixtures.

Tests run against an isolated on-disk SQLite database in a temp directory, not
the developer's real one. The environment is configured before any application
module is imported so the settings singleton picks it up.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before app.core.config is imported anywhere.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oip_tests_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("DETECTOR_BACKEND", "mock")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("GEE_ENABLED", "false")

from app.core.database import SessionLocal, engine, init_db  # noqa: E402
from app.models import Base  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    """Create the schema once for the whole test session."""
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator[Session]:
    """A clean session with all tables truncated between tests."""
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        yield session


@pytest.fixture
def session() -> Iterator[Session]:
    """A read-only-ish session that does NOT truncate.

    Use this alongside a client fixture to inspect what the API wrote.
    Requesting the ``db`` fixture instead would wipe the tables the client
    just populated, and assertions on "no rows" would then pass vacuously.
    """
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient with a clean database and the application lifespan run.

    Tables are truncated before the lifespan runs so start-up bootstrap
    (regions, model registry) repopulates them, giving each test the same
    starting state regardless of execution order.
    """
    from app.main import app

    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded_client(client: TestClient) -> TestClient:
    """A client whose database has been through one ingestion cycle."""
    client.post("/api/v1/satellite/ingest")
    return client
