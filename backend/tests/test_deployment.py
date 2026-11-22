"""Deployment guards: a fresh container serves, it does not rebuild.

The rule these tests defend is the one that decides whether this can be
deployed at all: **starting the application must not ingest anything.** Data
arrives through explicit jobs and persists in the database; a web task that
rebuilt it would take twelve minutes to answer a health check and would hit
public APIs on every scale-out.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.core.config import settings
from app.core.dbinfo import BackendInfo, SpatialBackendUnavailableError, report_backend
from app.models.water import (
    DataSource,
    MonitoringStation,
    WaterBody,
    WaterQualityObservation,
)
from app.water.cli import bootstrap_in_background
from fastapi.testclient import TestClient


def _one_observation(db) -> None:
    source = DataSource(key="s", name="s", organisation="s")
    body = WaterBody(slug="b", name="B", normalized_name="B", water_type="river")
    db.add_all([source, body])
    db.flush()
    station = MonitoringStation(
        station_code="s1",
        name="s1",
        slug="s1",
        source_id=source.id,
        water_body_id=body.id,
    )
    db.add(station)
    db.flush()
    db.add(
        WaterQualityObservation(
            station_id=station.id,
            water_body_id=body.id,
            source_id=source.id,
            parameter="bod",
            observed_at=datetime(2025, 4, 21, tzinfo=UTC),
            value=2.0,
            retrieved_at=datetime.now(UTC),
        )
    )
    db.commit()


class TestStartupDoesNotIngest:
    def test_no_bootstrap_when_unconfigured(self, db, monkeypatch):
        """The production default is empty, so nothing is fetched."""
        monkeypatch.setattr(settings, "water_bootstrap_states", "")
        assert bootstrap_in_background() is None

    def test_no_bootstrap_when_data_exists(self, db, monkeypatch):
        """A database that already holds observations is served as-is."""
        _one_observation(db)
        monkeypatch.setattr(settings, "water_bootstrap_states", "MH")
        assert bootstrap_in_background() is None

    def test_health_is_immediate_and_names_the_backend(self, client: TestClient):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        database = next(
            c for c in response.json()["components"] if c["name"] == "database"
        )
        assert database["available"] is True
        assert database["detail"]  # says which backend, e.g. "sqlite development mode"


class TestProductionGuards:
    def test_production_without_postgres_fails_loudly(self, monkeypatch):
        """Silently serving SQLite in production is the failure to avoid."""
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(
            "app.core.dbinfo.backend_info",
            lambda: BackendInfo("sqlite", None, None),
        )
        with pytest.raises(SpatialBackendUnavailableError, match="requires PostgreSQL"):
            report_backend()

    def test_production_without_postgis_fails_loudly(self, monkeypatch):
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(
            "app.core.dbinfo.backend_info",
            lambda: BackendInfo("postgresql", "16.4", None),
        )
        with pytest.raises(
            SpatialBackendUnavailableError, match="PostGIS is not installed"
        ):
            report_backend()

    def test_development_on_sqlite_is_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "environment", "development")
        monkeypatch.setattr(
            "app.core.dbinfo.backend_info",
            lambda: BackendInfo("sqlite", None, None),
        )
        info = report_backend()
        assert "development mode" in info.label

    def test_production_with_postgis_but_no_geometry_columns_fails_loudly(
        self, monkeypatch
    ):
        """The extension alone is not a working spatial schema.

        A database created by ``create_all`` has the extension (it is
        installed in the template or by hand) and none of the geometry
        columns, which the hand-written migration adds. Reporting that as
        spatial-ready made every spatial query fail on a missing column.
        """
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(
            "app.core.dbinfo.backend_info",
            lambda: BackendInfo("postgresql", "16.4", "3.4", geometry_columns=0),
        )
        with pytest.raises(
            SpatialBackendUnavailableError, match="migrations have not been run"
        ):
            report_backend()

    def test_a_partly_migrated_schema_is_not_spatial_ready(self):
        partial = BackendInfo("postgresql", "16.4", "3.4", geometry_columns=3)
        assert partial.has_postgis is True
        assert partial.spatial_ready is False
        assert "3 of 6 geometry columns" in partial.label

    def test_backend_label_reads_plainly(self):
        ready = BackendInfo("postgresql", "16.4", "3.4", geometry_columns=6)
        assert ready.label == "PostgreSQL 16.4 + PostGIS 3.4"
        assert ready.spatial_ready is True
        assert "WITHOUT PostGIS" in BackendInfo("postgresql", "16.4", None).label
        assert (
            "migrations have not run"
            in BackendInfo("postgresql", "16.4", "3.4", geometry_columns=0).label
        )


class TestTheBackendProbeNoticesAMigration:
    """The one question whose answer changes under a running process.

    The deployment order is: start the task, then run the migrate job. With a
    permanently cached probe the task reported "0 of 6 geometry columns
    exist" for the rest of its life while serving a migrated database.
    """

    def test_the_probe_result_expires(self, monkeypatch):
        from app.core import dbinfo

        dbinfo.forget_backend_cache()
        calls = {"n": 0}

        def counted(_engine):
            calls["n"] += 1
            return BackendInfo("postgresql", "16.4", "3.4", geometry_columns=calls["n"])

        monkeypatch.setattr(dbinfo, "_probe_uncached", counted)

        clock = {"t": 1000.0}
        monkeypatch.setattr(dbinfo, "monotonic", lambda: clock["t"])

        engine = object()
        assert dbinfo.backend_for(engine).geometry_columns == 1
        assert dbinfo.backend_for(engine).geometry_columns == 1, "cached"
        assert calls["n"] == 1

        clock["t"] += dbinfo.PROBE_TTL_SECONDS + 1
        assert dbinfo.backend_for(engine).geometry_columns == 2, "re-probed"
        assert calls["n"] == 2
        dbinfo.forget_backend_cache()

    def test_forgetting_the_cache_forces_a_fresh_probe(self, monkeypatch):
        from app.core import dbinfo

        dbinfo.forget_backend_cache()
        calls = {"n": 0}

        def counted(_engine):
            calls["n"] += 1
            return BackendInfo("postgresql", "16.4", "3.4", geometry_columns=6)

        monkeypatch.setattr(dbinfo, "_probe_uncached", counted)
        engine = object()
        dbinfo.backend_for(engine)
        dbinfo.forget_backend_cache()
        dbinfo.backend_for(engine)
        assert calls["n"] == 2
        dbinfo.forget_backend_cache()
