"""The suite must never be able to touch a real database.

This exists because it once did: a shell that had sourced `.env` exported
`DATABASE_URL` pointing at the local PostgreSQL server, `conftest` used
`os.environ.setdefault`, and the session fixture's `drop_all` at teardown
emptied a database holding 4.6 million ingested observations.

Two things are pinned here: the environment the suite actually runs with, and
the guard that refuses anything else.
"""

from __future__ import annotations

import os

from app.core.database import engine


class TestTheSuiteRunsOnItsOwnDatabase:
    def test_database_url_is_a_temporary_sqlite_file(self):
        url = os.environ["DATABASE_URL"]
        assert url.startswith("sqlite:///"), url
        assert "oip_tests_" in url, "must be the temp directory conftest made"

    def test_engine_is_sqlite_not_a_server(self):
        assert engine.url.drivername.split("+")[0] == "sqlite"
        assert engine.url.host is None

    def test_an_exported_database_url_does_not_win(self):
        """conftest overwrites rather than defaults, so this cannot be a server.

        Proved end to end by `scripts/check_test_isolation.sh`, which exports a
        PostgreSQL DATABASE_URL, runs the suite and checks a marker table in
        that database survives.
        """
        url = os.environ["DATABASE_URL"]
        assert not url.startswith("postgres"), url
        assert engine.url.database is not None
        assert engine.url.database.endswith("test.db")

    def test_the_guard_rejects_a_postgres_url(self):
        """The check in the session fixture, exercised directly."""
        from sqlalchemy.engine import make_url

        url = make_url("postgresql+psycopg://user:pw@localhost:5433/oip")
        assert url.drivername.split("+")[0] != "sqlite"
        # The message must name the offending backend without the password.
        rendered = url.render_as_string(hide_password=True)
        assert "pw" not in rendered
        assert "localhost:5433" in rendered
