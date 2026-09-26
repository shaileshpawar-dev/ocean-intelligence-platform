"""Shared pytest fixtures.

Tests run against an isolated on-disk SQLite database in a temp directory, not
the developer's real one. The environment is configured before any application
module is imported so the settings singleton picks it up.

``DATABASE_URL`` is **overwritten**, not defaulted. It used to be a
``setdefault``, which meant a shell that had sourced ``.env`` -- where
``DATABASE_URL`` points at the local PostgreSQL -- ran the whole suite against
that server, and the session fixture's ``drop_all`` at teardown emptied it.
Nothing in this suite may ever touch a real database, so the value is replaced
and then checked below.

To exercise PostgreSQL and PostGIS, set ``TEST_POSTGIS_URL`` instead: the
tests in ``test_postgis.py`` create their own throwaway database from it and
drop that, never the database named in the URL.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before app.core.config is imported anywhere.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oip_tests_"))
_TEST_DATABASE_URL = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
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
    """Create the schema once for the whole test session.

    The guard is the important part. This fixture drops every table at the end
    of the session, so it refuses to run anywhere but the throwaway SQLite
    file created above. Once, it ran against a live PostgreSQL server because
    the shell had exported ``DATABASE_URL``; the cost was a dataset that took
    hours to ingest.
    """
    url = engine.url
    # Compare as paths: SQLite reports forward slashes even on Windows.
    same_file = bool(url.database) and Path(url.database) == (_TMP_DIR / "test.db")
    if url.drivername.split("+")[0] != "sqlite" or not same_file:
        raise RuntimeError(
            "The test suite drops every table at teardown and must only ever "
            f"run against its own temporary SQLite file. It is pointed at "
            f"{url.render_as_string(hide_password=True)}. Do not set "
            "DATABASE_URL for tests; use TEST_POSTGIS_URL to exercise PostGIS."
        )
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
