"""End-to-end API tests.

Beyond status codes, these assert the platform's provenance contract: no
response may carry simulated data without saying so.
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient


class TestSystem:
    def test_root_banner(self, client: TestClient) -> None:
        body = client.get("/").json()
        assert body["name"]
        assert body["api"] == "/api/v1"

    def test_health_reports_every_component(self, client: TestClient) -> None:
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        names = {c["name"] for c in body["components"]}
        assert "database" in names
        assert any(n.startswith("satellite:") for n in names)
        assert any(n.startswith("detector:") for n in names)

    def test_health_ok_even_without_optional_services(self, client: TestClient) -> None:
        """Missing GEE or LLM credentials must degrade, not break."""
        assert client.get("/api/v1/health").status_code == 200

    def test_request_id_is_echoed(self, client: TestClient) -> None:
        response = client.get("/api/v1/health")
        assert response.headers.get("X-Request-ID")

    def test_supplied_request_id_is_preserved(self, client: TestClient) -> None:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-me-123"})
        assert response.headers["X-Request-ID"] == "trace-me-123"


class TestIngestion:
    def test_ingest_returns_a_summary(self, client: TestClient) -> None:
        body = client.post("/api/v1/satellite/ingest").json()
        assert body["cells_requested"] > 0
        assert body["observations_stored"] > 0

    def test_negatives_are_counted_not_discarded(self, client: TestClient) -> None:
        """Cells found clean are recorded; they are a result, not a gap."""
        body = client.post("/api/v1/satellite/ingest").json()
        assert body["negatives_recorded"] > 0

    def test_ingestion_is_idempotent_on_observations(self, client: TestClient) -> None:
        """Re-ingesting the same window must not duplicate measurements."""
        client.post("/api/v1/satellite/ingest")
        before = client.get("/api/v1/overview").json()["observations"]
        client.post("/api/v1/satellite/ingest")
        after = client.get("/api/v1/overview").json()["observations"]
        assert after == before

    def test_ingestion_is_idempotent_on_events(self, client: TestClient) -> None:
        """Re-ingesting must not duplicate detections either.

        Event ids are derived from (observation, signature), so a scheduled
        sweep over unchanged scenes recognises what it already stored. A
        random id here would multiply events on every run.
        """
        client.post("/api/v1/satellite/ingest")
        before = client.get("/api/v1/overview").json()["total_events"]
        second = client.post("/api/v1/satellite/ingest").json()
        after = client.get("/api/v1/overview").json()["total_events"]
        assert after == before
        assert second["events_created"] == 0

    def test_refinement_is_idempotent_on_events(self, client: TestClient) -> None:
        """Refining the same cells twice must not duplicate their detections."""
        client.post("/api/v1/satellite/ingest")
        client.post("/api/v1/satellite/refine?max_cells=3")
        before = client.get("/api/v1/overview").json()["total_events"]
        second = client.post("/api/v1/satellite/refine?max_cells=3").json()
        after = client.get("/api/v1/overview").json()["total_events"]
        assert after == before
        assert second["events_created"] == 0


class TestProvenanceContract:
    """Simulated data must be undeniable in every response that carries it."""

    def test_zones_declare_simulated_data(self, seeded_client: TestClient) -> None:
        body = seeded_client.get("/api/v1/pollution-zones").json()
        provenance = body["provenance"]
        assert provenance["contains_simulated_data"] is True
        assert any("SIMULATED" in note for note in provenance["notes"])

    def test_every_simulated_item_is_individually_flagged(
        self, seeded_client: TestClient
    ) -> None:
        """A client filtering row-by-row must not be able to miss one."""
        body = seeded_client.get("/api/v1/pollution-events").json()
        if body["provenance"]["contains_simulated_data"]:
            assert all(item["is_simulated"] for item in body["items"])

    def test_provenance_lists_evidence_levels(self, seeded_client: TestClient) -> None:
        body = seeded_client.get("/api/v1/pollution-events").json()
        assert body["provenance"]["evidence_levels"]


class TestPollutionEndpoints:
    def test_zones_include_clean_cells(self, seeded_client: TestClient) -> None:
        """Observed-and-clean cells appear with a null signature."""
        items = seeded_client.get("/api/v1/pollution-zones").json()["items"]
        assert any(z["signature"] is None for z in items)

    def test_events_carry_caveats(self, seeded_client: TestClient) -> None:
        items = seeded_client.get("/api/v1/pollution-events").json()["items"]
        if items:
            assert items[0]["caveats"]

    def test_confidence_never_claims_calibration(self, seeded_client: TestClient) -> None:
        items = seeded_client.get("/api/v1/pollution-events").json()["items"]
        assert all(i["confidence_is_calibrated"] is False for i in items)

    def test_event_detail_includes_risk_and_observation(
        self, seeded_client: TestClient
    ) -> None:
        items = seeded_client.get("/api/v1/pollution-events").json()["items"]
        if not items:
            return
        detail = seeded_client.get(
            f"/api/v1/pollution-events/{items[0]['event_id']}"
        ).json()
        assert detail["risk_assessment"]["contributions"]
        assert detail["observation"]["mean_db"] is not None
        assert "distance_to_coast_km" in detail["geographic_context"]

    def test_unknown_event_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/pollution-events/nope").status_code == 404

    def test_severity_filter(self, seeded_client: TestClient) -> None:
        items = seeded_client.get(
            "/api/v1/pollution-events", params={"severity": "HIGH"}
        ).json()["items"]
        assert all(i["severity"] == "HIGH" for i in items)

    def test_alerts_are_ordered_by_risk(self, seeded_client: TestClient) -> None:
        items = seeded_client.get("/api/v1/alerts").json()["items"]
        scores = [i["risk_score"] for i in items if i["risk_score"] is not None]
        assert scores == sorted(scores, reverse=True)


class TestRiskEndpoint:
    def test_contributions_sum_to_the_score(self, seeded_client: TestClient) -> None:
        """The API's own numbers must reconstruct the score it reports."""
        items = seeded_client.get("/api/v1/pollution-events").json()["items"]
        if not items:
            return
        risk = seeded_client.get(f"/api/v1/risk/{items[0]['event_id']}").json()
        awarded = sum(c["points"] for c in risk["contributions"])
        available = sum(c["max_points"] for c in risk["contributions"])
        assert risk["score"] == round(awarded / available * 100, 2)

    def test_unknown_event_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/risk/nope").status_code == 404


class TestAnalytics:
    def test_trends_report_coverage(self, seeded_client: TestClient) -> None:
        """Coverage ratio distinguishes a quiet week from an unobserved one."""
        items = seeded_client.get("/api/v1/trends", params={"days": 30}).json()["items"]
        for item in items:
            assert 0.0 <= item["coverage_ratio"] <= 1.0

    def test_forecast_declares_its_scope(self, seeded_client: TestClient) -> None:
        """Never a dispersion forecast."""
        items = seeded_client.get("/api/v1/pollution-zones").json()["items"]
        code = items[0]["region_code"]
        body = seeded_client.get(f"/api/v1/forecast/{code}").json()
        assert body["forecast_kind"] == "detection_activity"
        assert any("not the physical movement" in c for c in body["caveats"])

    def test_forecast_refuses_unknown_model(self, seeded_client: TestClient) -> None:
        items = seeded_client.get("/api/v1/pollution-zones").json()["items"]
        code = items[0]["region_code"]
        response = seeded_client.get(
            f"/api/v1/forecast/{code}", params={"model": "transformer9000"}
        )
        assert response.status_code == 400

    def test_forecast_unknown_region_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/forecast/atlantis").status_code == 404

    def test_overview_counts(self, seeded_client: TestClient) -> None:
        body = seeded_client.get("/api/v1/overview").json()
        assert body["observations"] > 0
        assert "contains_simulated_data" in body


class TestModelRegistry:
    def test_models_are_registered(self, client: TestClient) -> None:
        names = {m["name"] for m in client.get("/api/v1/models").json()}
        assert "sar-dark-formation" in names

    def test_unevaluated_metrics_are_null_not_invented(self, client: TestClient) -> None:
        """A registry entry with no evaluation must report null, never 0.87."""
        for model in client.get("/api/v1/models").json():
            if model["metrics_source"] is None:
                assert model["map50"] is None
                assert model["precision"] is None

    def test_detectors_declare_supported_signatures(self, client: TestClient) -> None:
        detectors = client.get("/api/v1/models/detectors").json()
        sar = next(d for d in detectors if d["name"] == "sar-dark-formation")
        assert "plastic_debris_signature" not in sar["supported_signatures"]

    def test_unknown_model_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/models/ghost/1.0").status_code == 404


class TestMonitoring:
    def test_metrics_report_zero_not_fake_latency(self, client: TestClient) -> None:
        body = client.get("/api/v1/metrics").json()
        assert body["latency"]["n"] == 0
        assert body["latency"]["mean_ms"] is None

    def test_drift_reports_insufficient_data_without_history(
        self, client: TestClient
    ) -> None:
        """A verdict requires samples; otherwise say so."""
        body = client.get("/api/v1/drift").json()
        assert body["overall_status"] == "insufficient_data"
        assert "human review" in body["action"]


class TestDetectEndpoint:
    def test_rejects_unsupported_file_type(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/detect",
            files={"file": ("payload.exe", io.BytesIO(b"x"), "application/octet-stream")},
        )
        assert response.status_code == 415

    def test_mock_detector_output_is_labelled_simulated(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/detect",
            files={"file": ("scene.png", io.BytesIO(b"fake-bytes"), "image/png")},
        )
        assert response.status_code == 200
        body = response.json()
        assert any("SIMULATED" in note for note in body["notes"])

    def test_ungeolocated_detections_say_so(self, client: TestClient) -> None:
        """Better an absent coordinate than a fabricated one."""
        body = client.post(
            "/api/v1/detect",
            files={"file": ("scene.png", io.BytesIO(b"fake-bytes"), "image/png")},
        ).json()
        assert any("not geolocated" in note for note in body["notes"])
        for detection in body["detections"]:
            assert detection["latitude"] is None

    def test_prediction_is_logged_for_metrics(self, client: TestClient) -> None:
        client.post(
            "/api/v1/detect",
            files={"file": ("scene.png", io.BytesIO(b"fake-bytes"), "image/png")},
        )
        assert client.get("/api/v1/metrics").json()["volume"]["total_requests"] >= 1


class TestModelRegistrySync:
    """Registry rows must track code changes without destroying evidence."""

    def test_descriptive_fields_are_refreshed_on_restart(self, client, session):
        """Correcting the class list must reach an existing database.

        The class map was wrong (class 3 recorded as 'marine_debris' when the
        checkpoint emits 'chemical_pollution'). Insert-only seeding would
        leave that stale forever.
        """
        from app.demo.seed import bootstrap
        from app.models import ModelVersion
        from sqlalchemy import select

        row = session.scalar(
            select(ModelVersion).where(ModelVersion.name == "yolo-pollution-detector")
        )
        assert row is not None
        row.class_names = ["stale", "values"]
        session.commit()

        bootstrap(session)
        session.refresh(row)
        assert "chemical_pollution" in row.class_names
        assert "marine_debris" not in row.class_names

    def test_measured_metrics_are_never_overwritten(self, client, session):
        """Seeding must not clobber metrics an evaluation run earned."""
        from app.demo.seed import bootstrap
        from app.models import ModelVersion
        from sqlalchemy import select

        row = session.scalar(
            select(ModelVersion).where(ModelVersion.name == "yolo-pollution-detector")
        )
        row.map50 = 0.873
        row.precision = 0.91
        row.metrics_source = "evaluate_detector.py @ test"
        session.commit()

        bootstrap(session)
        session.refresh(row)
        assert row.map50 == 0.873
        assert row.precision == 0.91
        assert row.metrics_source == "evaluate_detector.py @ test"


class TestConsoleServing:
    """The SPA mount must not disturb the API contract."""

    def test_root_still_returns_json_for_api_clients(self, client) -> None:
        """A redirect for everyone would have broken every existing client."""
        body = client.get("/", headers={"Accept": "application/json"}).json()
        assert body["api"] == "/api/v1"
        assert body["name"]

    def test_browser_is_sent_to_the_console_when_built(self, client) -> None:
        from app.main import SPA_INDEX

        response = client.get(
            "/", headers={"Accept": "text/html"}, follow_redirects=False
        )
        if SPA_INDEX.is_file():
            assert response.status_code == 307
            assert response.headers["location"] == "/app"
        else:
            assert response.status_code == 200

    def test_deep_links_reach_the_spa_not_a_404(self, client) -> None:
        """React Router uses browser history; /app/* must serve index.html."""
        from app.main import SPA_INDEX

        response = client.get("/app/events/evt_example")
        if SPA_INDEX.is_file():
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
        else:
            assert response.status_code == 503

    def test_api_routes_are_unaffected_by_the_spa_mount(self, client) -> None:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/overview").status_code == 200

    def test_index_is_not_cached_but_assets_are(self, client) -> None:
        """A cached index.html points at chunk hashes a redeploy has removed.

        Getting this wrong strands returning browsers on "Failed to fetch
        dynamically imported module" while the server looks healthy.
        """
        from app.main import SPA_DIR, SPA_INDEX

        if not SPA_INDEX.is_file():
            return

        index = client.get("/app")
        assert "no-cache" in index.headers.get("cache-control", "")

        assets = SPA_DIR / "assets"
        if assets.is_dir():
            first = next((p for p in assets.iterdir() if p.is_file()), None)
            if first:
                served = client.get(f"/app/assets/{first.name}")
                assert served.status_code == 200
                assert "immutable" in served.headers.get("cache-control", "")
