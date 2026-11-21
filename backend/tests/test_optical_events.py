"""Events from real index readings: what triggers one, and what it claims.

Three things worth holding still.

A reading that did not clear the water-pixel floor must never become an
event. The floor exists because an index over eight pixels is arithmetic
rather than a measurement, and an event is a far louder artefact than a
dimmed table row -- it reaches the map, the alert list and the risk ranking.

A region without enough history of its own raises nothing, rather than
falling back to a figure borrowed from a different stretch of water. That
fallback is the exact error the per-region method exists to avoid.

And the threshold is a percentile of the region's own twelve months, so a
detection means "unusual for this water as measured here" -- a much weaker
claim than "polluted". The sentence that says so travels on every event.

**A property of the method, which these tests are built around:** a 99th
percentile always flags roughly one percent of the very readings it was
computed from. That is inherent to percentile thresholding, not a bug, so
the tests below measure the *change* a new reading causes rather than the
absolute count.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.models import PollutionEvent, Region
from app.models.enums import DetectionMethod, PollutionSignature
from app.models.optical import OpticalIndexObservation
from app.services.optical_events import (
    MIN_BASELINE_READINGS,
    NDCI_LITERATURE_THRESHOLD,
    RELATIVE_THRESHOLD_CAVEAT,
    WATER_PIXEL_FLOOR,
    build_optical_events,
    compute_baselines,
    optical_event_id,
)

QUIET = {"ndci_mean": -0.05, "ndti_mean": -0.20, "fdi_mean": 0.005}
#: Far above any plausible baseline, so a trigger is unambiguous.
LOUD = 0.9


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
        "ndci_p50": -0.05,
        "ndti_p50": -0.20,
        "fdi_p90": 0.01,
        "water_pixels": 6000,
        "total_pixels": 10000,
        "max_cloud_pct": 30,
        "evidence_level": "OBSERVED",
        "source": "Copernicus Sentinel-2 L2A",
        **QUIET,
    }
    return OpticalIndexObservation(**{**base, **overrides})


def _baseline(db, region: Region, *, n: int = MIN_BASELINE_READINGS) -> None:
    """A twelve-month history with realistic spread.

    Deliberately not flat. A constant series puts the 99th percentile *on*
    every value, so a ``>=`` comparison fires on all of them -- which is
    arithmetically correct and makes the fixture useless. Real water varies,
    so the baseline spans a modest range with :data:`QUIET` at the bottom,
    leaving an ordinary reading comfortably below the threshold.
    """
    for offset in range(n):
        spread = offset / max(n - 1, 1)  # 0 -> 1 across the series
        db.add(
            _reading(
                region,
                observed_on=date(2026, 11, 19) - timedelta(days=offset),
                ndci_mean=QUIET["ndci_mean"] + spread * 0.10,
                ndti_mean=QUIET["ndti_mean"] + spread * 0.10,
                fdi_mean=QUIET["fdi_mean"] + spread * 0.02,
            )
        )
    db.commit()


def _settle(db) -> int:
    """Raise the baseline's own inherent top 1%, and report how many.

    Leaves the database in the state a second run would see, so a following
    call to the builder reports only what a *new* reading caused.
    """
    return build_optical_events(db)["events_created"]


class TestWhatRaisesAnEvent:
    """One signature per index, each above that region's own percentile."""

    def test_another_ordinary_reading_raises_nothing_new(self, db, region):
        _baseline(db, region)
        _settle(db)

        db.add(_reading(region))
        db.commit()

        assert build_optical_events(db)["events_created"] == 0

    def test_a_region_without_enough_history_raises_nothing(self, db, region):
        """No baseline means no judgement -- and deliberately no fallback to
        another region's water, which is the error this guards."""
        _baseline(db, region, n=MIN_BASELINE_READINGS - 5)
        db.add(_reading(region, ndci_mean=LOUD, fdi_mean=LOUD, ndti_mean=LOUD))
        db.commit()

        summary = build_optical_events(db)

        assert summary["events_created"] == 0
        assert summary["regions_with_baseline"] == 0

    def test_elevated_ndci_raises_an_algal_bloom(self, db, region):
        _baseline(db, region)
        _settle(db)

        db.add(_reading(region, ndci_mean=LOUD))
        db.commit()
        summary = build_optical_events(db)

        assert summary["by_signature"] == {
            str(PollutionSignature.ALGAE_BLOOM_SIGNATURE): 1
        }

    def test_elevated_fdi_raises_floating_material_not_plastic(self, db, region):
        """The signature names what the index can support. FDI cannot
        identify a material, so the event must not claim one."""
        _baseline(db, region)
        _settle(db)

        db.add(_reading(region, fdi_mean=LOUD))
        db.commit()
        build_optical_events(db)

        event = (
            db.query(PollutionEvent)
            .filter(PollutionEvent.signature == str(PollutionSignature.FLOATING_MATERIAL))
            .first()
        )
        assert event is not None
        assert "plastic" not in event.signature
        assert any("not evidence of plastic" in c.lower() for c in event.caveats)

    def test_elevated_ndti_raises_a_turbidity_plume(self, db, region):
        _baseline(db, region)
        _settle(db)

        db.add(_reading(region, ndti_mean=LOUD))
        db.commit()
        summary = build_optical_events(db)

        assert summary["by_signature"] == {str(PollutionSignature.TURBIDITY_PLUME): 1}

    def test_one_reading_can_raise_several_signatures(self, db, region):
        """Three indices, three independent questions about the same water."""
        _baseline(db, region)
        _settle(db)

        db.add(_reading(region, ndci_mean=LOUD, fdi_mean=LOUD, ndti_mean=LOUD))
        db.commit()

        assert build_optical_events(db)["events_created"] == 3


class TestThresholdsAreRegional:
    """The point of the method: each region judged against its own water."""

    def test_two_regions_get_different_thresholds(self, db, region):
        turbid = Region(
            code="krishna_godavari_offshore_se",
            name="Krishna-Godavari Offshore SE",
            min_lon=82.0,
            min_lat=15.0,
            max_lon=83.4,
            max_lat=16.3,
            centroid_lat=15.65,
            centroid_lon=82.7,
        )
        db.add(turbid)
        db.commit()

        _baseline(db, region)
        for offset in range(MIN_BASELINE_READINGS):
            db.add(
                _reading(
                    turbid,
                    observed_on=date(2026, 11, 19) - timedelta(days=offset),
                    ndti_mean=0.25,
                )
            )
        db.commit()

        baselines = compute_baselines(db)

        quiet_threshold = baselines[region.id].percentiles["NDTI"]
        turbid_threshold = baselines[turbid.id].percentiles["NDTI"]
        assert turbid_threshold > quiet_threshold, (
            "a naturally turbid cell must get a higher bar, or it is flagged "
            "every day for being where a river is"
        )

    def test_a_reading_normal_for_its_region_is_not_an_anomaly(self, db, region):
        """0.25 NDTI is unremarkable off a delta and extraordinary offshore.
        A single platform-wide threshold cannot express that."""
        _baseline(db, region)
        baseline = compute_baselines(db)[region.id]

        assert 0.25 > baseline.percentiles["NDTI"], "quiet water: 0.25 is loud"


class TestTheWaterFloorHolds:
    """A reading over a handful of pixels must not reach the map."""

    def test_a_low_water_reading_raises_nothing_however_extreme(self, db, region):
        """The real failure this guards: an 8-pixel cell produced an FDI ten
        times every other reading. As a dimmed table row that is a curiosity;
        as an event it is an alert."""
        _baseline(db, region)
        _settle(db)

        db.add(
            _reading(
                region,
                water_pixels=WATER_PIXEL_FLOOR - 1,
                fdi_mean=LOUD,
                ndci_mean=LOUD,
            )
        )
        db.commit()
        summary = build_optical_events(db)

        assert summary["events_created"] == 0
        assert summary["readings_below_water_floor"] == 1


class TestWhatTheEventClaims:
    """Provenance, and the limits of a per-region percentile."""

    @pytest.fixture
    def event(self, db, region) -> PollutionEvent:
        _baseline(db, region)
        _settle(db)
        db.add(_reading(region, ndci_mean=LOUD))
        db.commit()
        build_optical_events(db)
        event = (
            db.query(PollutionEvent)
            .filter(
                PollutionEvent.signature
                == str(PollutionSignature.ALGAE_BLOOM_SIGNATURE)
            )
            .order_by(PollutionEvent.id.desc())
            .first()
        )
        assert event is not None, "the loud NDCI reading should have raised one"
        return event

    def test_it_leads_with_the_anomaly_sentence(self, event):
        """The one line stopping a reader taking this for an incident."""
        assert event.caveats[0].startswith("Statistical anomaly: top 1% of this region")
        assert "Sentinel-2 NDCI" in event.caveats[0]

    def test_it_says_the_threshold_is_relative_not_regulatory(self, event):
        assert RELATIVE_THRESHOLD_CAVEAT in event.caveats
        assert "not a confirmed pollution incident" in RELATIVE_THRESHOLD_CAVEAT

    def test_it_records_the_baseline_it_was_judged_against(self, event):
        baseline = event.extra["baseline"]

        assert baseline["method"] == "per-region 99th percentile"
        assert baseline["baseline_readings"] >= MIN_BASELINE_READINGS
        assert baseline["baseline_from"] and baseline["baseline_to"]

    def test_an_ndci_event_also_reports_the_absolute_check(self, event):
        """"Unusual here" and "high in anyone's terms" are different
        questions, and for chlorophyll both can be answered."""
        check = event.extra["literature_check"]

        assert check["threshold"] == NDCI_LITERATURE_THRESHOLD
        assert check["exceeds"] is True
        assert "absolute" in check["source"]

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


class TestRerunning:
    """Re-running over the same readings must not multiply events."""

    def test_the_event_id_is_deterministic(self):
        first = optical_event_id("palk_bay", date(2026, 11, 20), "turbidity_plume")
        second = optical_event_id("palk_bay", date(2026, 11, 20), "turbidity_plume")

        assert first == second

    def test_a_second_run_creates_nothing_new(self, db, region):
        _baseline(db, region)
        db.add(_reading(region, ndci_mean=LOUD))
        db.commit()
        first = build_optical_events(db)["events_created"]

        second = build_optical_events(db)

        assert first > 0
        assert second["events_created"] == 0
        assert second["already_present"] == first
