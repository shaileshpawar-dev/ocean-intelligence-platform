"""Liveness, readiness and health answer three different questions.

A load balancer needs to know whether to send traffic here; an orchestrator
needs to know whether to restart the process. The endpoint used to answer
both with HTTP 200 and a word in the body, so a task with no database stayed
in rotation and kept returning errors to users.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


@pytest.fixture
def dead_database(monkeypatch):
    """Every database call raises, as it would if RDS were unreachable."""

    def boom(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr("sqlalchemy.orm.Session.execute", boom)


class TestLiveness:
    def test_liveness_is_200_and_names_the_app(self, client: TestClient):
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_liveness_survives_a_dead_database(self, client: TestClient, dead_database):
        """The process is alive even when its database is not.

        Restarting the container cannot fix an unreachable database, so
        liveness must not fail and trigger a restart loop.
        """
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


class TestReadiness:
    def test_ready_when_the_database_answers(self, client: TestClient):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["database"]
        assert "spatial_sql" in body

    def test_not_ready_and_503_when_the_database_is_gone(
        self, client: TestClient, dead_database
    ):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503, "the load balancer must stop sending traffic"
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["reason"] == "database_unavailable"

    def test_readiness_does_not_require_postgis(self, client: TestClient):
        """SQLite development mode is ready; it just has no spatial SQL."""
        body = client.get("/api/v1/health/ready").json()
        assert body["status"] == "ready"
        assert body["spatial_sql"] is False


class TestHealth:
    def test_health_is_200_with_a_working_database(self, client: TestClient):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_is_503_when_the_database_is_unusable(
        self, client: TestClient, dead_database
    ):
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        database = next(c for c in body["components"] if c["name"] == "database")
        assert database["available"] is False

    def test_missing_optional_components_do_not_make_it_unhealthy(
        self, client: TestClient
    ):
        """No LLM configured is a fact about the deployment, not an outage."""
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        llm = next(c for c in body["components"] if c["name"].startswith("llm:"))
        assert llm["available"] is False
