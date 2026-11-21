"""Events from real index readings: what triggers one, and what it claims.

Two things worth holding still.

A reading that did not clear the water-pixel floor must never become an
event. The floor exists because an index over eight pixels is arithmetic
rather than a measurement, and an event is a far louder artefact than a
dimmed table row -- it reaches the map, the alert list and the risk ranking.

And the thresholds are percentiles of this platform's own distribution for
two of the three indices. That makes a detection "unusual for these waters
as measured here", which is a different and much weaker claim than
"polluted". The caveat that says so travels on every event, and this pins
it there.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.models import PollutionEvent, Region
from app.models.enums import DetectionMethod, PollutionSignature
from app.models.optical import OpticalIndexObservation
from app.services.optical_events import (
    FDI_FLOATING,
    NDCI_BLOOM,
    NDTI_PLUME,
    RELATIVE_THRESHOLD_CAVEAT,
    WATER_PIXEL_FLOOR,
    build_optical_events,
    optical_event_id,
)


@pytest.fixture
def region(db) -> Region:
    """One monitored cell with real geography."""
    row = Region(
        code="gulf_of_mannar",
        name="Gulf of Mannar",
        min_lon=78.5,
        min_lat=8.4,
        max_lon=79.6,
        max_lat=9.4,
        centroid_lat=8.9,
        centroid_lon=79.05,
        distance_to_coast_km=12.0,
        nearest_protected_area="Gulf of Mannar Marine National Park",
        distance_to_protected_area_km=8.0,
    )
    db.add(row)
    db.commit()
    return row


def _reading(region: Region, **overrides) -> OpticalIndexObservation:
    base = {
        "region_id": region.id,
        "observed_on": date(2026, 11, 20),
        "ndci_mean": -0.05,
        "ndci_p50": -0.05,
        "ndti_mean": -0.20,
        "ndti_p50": -0.20,
        "fdi_mean": 0.005,
        "fdi_p90": 0.01,
        "water_pixels": 6000,
        "total_pixels": 10000,
        "max_cloud_pct": 30,
        "evidence_level": "OBSERVED",
        "source": "Copernicus Sentinel-2 L2A",
    }
    return OpticalIndexObservation(**{**base, **overrides})


class TestWhatRaisesAnEvent:
    """One signature per index, each above its own threshold."""

    def test_an_ordinary_reading_raises_nothing(self, db, region):
        db.add(_reading(region))
        db.commit()

        assert build_optical_events(db)["events_created"] == 0

    def test_elevated_ndci_raises_an_algal_bloom(self, db, region):
        db.add(_reading(region, ndci_mean=NDCI_BLOOM + 0.05))
        db.commit()

        summary = build_optical_events(db)

        assert summary["by_signature"] == {
            str(PollutionSignature.ALGAE_BLOOM_SIGNATURE): 1
        }

    def test_elevated_fdi_raises_floating_material_not_plastic(self, db, region):
        """The signature names what the index can support. FDI cannot
        identify a material, so the event must not claim one."""
        db.add(_reading(region, fdi_mean=FDI_FLOATING + 0.01))
        db.commit()

        build_optical_events(db)
        event = db.query(PollutionEvent).one()

        assert event.signature == str(PollutionSignature.FLOATING_MATERIAL)
        assert "plastic" not in event.signature
        assert any("not evidence of plastic" in c.lower() for c in event.caveats)

    def test_elevated_ndti_raises_a_turbidity_plume(self, db, region):
        db.add(_reading(region, ndti_mean=NDTI_PLUME + 0.01))
        db.commit()

        build_optical_events(db)

        assert db.query(PollutionEvent).one().signature == str(
            PollutionSignature.TURBIDITY_PLUME
        )

    def test_one_reading_can_raise_several_signatures(self, db, region):
        """Three indices, three independent questions about the same water."""
        db.add(
            _reading(
                region,
                ndci_mean=NDCI_BLOOM + 0.1,
                fdi_mean=FDI_FLOATING + 0.02,
                ndti_mean=NDTI_PLUME + 0.02,
            )
        )
        db.commit()

        assert build_optical_events(db)["events_created"] == 3


class TestTheWaterFloorHolds:
    """A reading over a handful of pixels must not reach the map."""

    def test_a_low_water_reading_raises_nothing_however_extreme(self, db, region):
        """The real failure this guards: an 8-pixel cell produced an FDI ten
        times every other reading. As a dimmed table row that is a curiosity;
        as an event it is an alert."""
        db.add(
            _reading(
                region,
                water_pixels=WATER_PIXEL_FLOOR - 1,
                fdi_mean=FDI_FLOATING * 5,
                ndci_mean=NDCI_BLOOM * 3,
            )
        )
        db.commit()

        summary = build_optical_events(db)

        assert summary["events_created"] == 0
        assert summary["readings_below_water_floor"] == 1


class TestWhatTheEventClaims:
    """Provenance, and the limits of a percentile threshold."""

    @pytest.fixture
    def event(self, db, region) -> PollutionEvent:
        db.add(_reading(region, ndci_mean=NDCI_BLOOM + 0.05))
        db.commit()
        build_optical_events(db)
        return db.query(PollutionEvent).one()

    def test_it_says_the_threshold_is_relative_not_absolute(self, event):
        """Without this the event reads as "this water is polluted"."""
        assert RELATIVE_THRESHOLD_CAVEAT in event.caveats
        assert "not a statement that the water is polluted" in (
            RELATIVE_THRESHOLD_CAVEAT.lower()
        )

    def test_it_carries_the_scene_date_index_and_attribution(self, event):
        extra = event.extra

        assert extra["index"] == "NDCI"
        assert extra["acquired_on"] == "2026-11-20"
        assert "Copernicus Sentinel data" in extra["attribution"]
        assert extra["is_real"] is True

    def test_it_is_detected_by_an_optical_index_not_simulated(self, event):
        assert event.detection_method == str(DetectionMethod.OPTICAL_INDEX)
        assert event.evidence_level == "DETECTED"

    def test_the_confidence_is_declared_uncalibrated(self, event):
        assert 0.0 < event.confidence <= 0.85
        assert any("uncalibrated" in c.lower() for c in event.caveats)

    def test_the_area_is_what_was_observed_not_the_anomaly(self, event):
        """A regional mean cannot give the extent of the thing it averaged."""
        assert event.estimated_area_km2 == 6000.0
        assert "not" in event.extra["area_basis"].lower()


class TestRerunning:
    """Re-running over the same readings must not multiply events."""

    def test_the_event_id_is_deterministic(self):
        first = optical_event_id("palk_bay", date(2026, 11, 20), "turbidity_plume")
        second = optical_event_id("palk_bay", date(2026, 11, 20), "turbidity_plume")

        assert first == second

    def test_a_second_run_creates_nothing_new(self, db, region):
        db.add(_reading(region, ndci_mean=NDCI_BLOOM + 0.05))
        db.commit()
        build_optical_events(db)

        second = build_optical_events(db)

        assert second["events_created"] == 0
        assert second["already_present"] == 1
        assert db.query(PollutionEvent).count() == 1
