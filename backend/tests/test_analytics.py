"""Tests for temporal analytics.

These guard the replacement for ``seed_history()``: aggregates must be derived
from stored data, and gaps must stay visible as gaps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import PollutionEvent, Region, SatelliteObservation, ZoneHistory
from app.models.enums import EvidenceLevel
from app.services.analytics_service import (
    get_region_series,
    get_trends,
    rebuild_history,
    region_trend_slopes,
    summary_counts,
)
from sqlalchemy import select


@pytest.fixture
def region(db) -> Region:
    region = Region(
        code="test_cell",
        name="Test Cell",
        parent_code="Test Sea",
        min_lon=10.0,
        min_lat=20.0,
        max_lon=12.0,
        max_lat=22.0,
        centroid_lat=21.0,
        centroid_lon=11.0,
    )
    db.add(region)
    db.commit()
    return region


def add_event(db, region: Region, days_ago: int, risk: float) -> None:
    """Insert one event with its backing observation."""
    when = datetime.now(UTC) - timedelta(days=days_ago)
    observation = SatelliteObservation(
        observation_id=f"obs_{region.code}_{days_ago}",
        region_id=region.id,
        collection="TEST",
        platform="test",
        acquired_at=when,
        mean_db=-15.0,
        evidence_level=str(EvidenceLevel.OBSERVED),
    )
    db.add(observation)
    db.flush()
    db.add(
        PollutionEvent(
            event_id=f"evt_{region.code}_{days_ago}",
            region_id=region.id,
            observation_id=observation.id,
            signature="dark_formation",
            detection_method="sar_dark_formation",
            evidence_level=str(EvidenceLevel.DETECTED),
            confidence=0.6,
            latitude=region.centroid_lat,
            longitude=region.centroid_lon,
            estimated_area_km2=100.0,
            risk_score=risk,
            severity="MEDIUM",
            detected_at=when,
        )
    )
    db.commit()


class TestHistoryRebuild:
    def test_aggregates_events_into_daily_buckets(self, db, region: Region) -> None:
        for offset, risk in [(3, 40.0), (2, 50.0), (1, 60.0)]:
            add_event(db, region, offset, risk)

        assert rebuild_history(db) == 3
        buckets = db.scalars(select(ZoneHistory)).all()
        assert {round(b.mean_risk_score) for b in buckets} == {40, 50, 60}

    def test_is_idempotent(self, db, region: Region) -> None:
        """Rebuilding twice must not double the aggregates."""
        add_event(db, region, 1, 50.0)
        first = rebuild_history(db)
        second = rebuild_history(db)
        assert first == second == 1

    def test_no_events_yields_no_buckets(self, db) -> None:
        """No data means no history, not zero-valued history."""
        assert rebuild_history(db) == 0


class TestTrends:
    def test_reports_coverage_not_just_values(self, db, region: Region) -> None:
        """Three observed days in a 30-day window is 10% coverage, stated."""
        for offset in (1, 2, 3):
            add_event(db, region, offset, 50.0)
        rebuild_history(db)

        trend = get_trends(db, days=30)[0]
        assert trend.coverage_days == 3
        assert trend.window_days == 30
        assert trend.to_dict()["coverage_ratio"] == pytest.approx(0.1)

    def test_change_and_slope_track_direction(self, db, region: Region) -> None:
        for offset, risk in [(4, 30.0), (3, 40.0), (2, 50.0), (1, 60.0)]:
            add_event(db, region, offset, risk)
        rebuild_history(db)

        trend = get_trends(db, days=30)[0]
        assert trend.change == pytest.approx(30.0)
        assert trend.slope_per_day > 0

    def test_window_excludes_older_data(self, db, region: Region) -> None:
        add_event(db, region, 100, 90.0)
        add_event(db, region, 1, 20.0)
        rebuild_history(db)

        trend = get_trends(db, days=7)[0]
        assert trend.coverage_days == 1
        assert trend.latest_risk == pytest.approx(20.0)


class TestTrendSlopes:
    def test_omits_regions_with_too_little_history(self, db, region: Region) -> None:
        """Two points is not a trend; the risk engine must see it as missing."""
        add_event(db, region, 1, 50.0)
        add_event(db, region, 2, 55.0)
        rebuild_history(db)
        assert region.id not in region_trend_slopes(db)

    def test_includes_regions_with_enough_history(self, db, region: Region) -> None:
        for offset, risk in [(4, 30.0), (3, 40.0), (2, 50.0), (1, 60.0)]:
            add_event(db, region, offset, risk)
        rebuild_history(db)
        assert region_trend_slopes(db)[region.id] > 0


class TestRegionSeries:
    def test_forward_fills_gaps_to_a_regular_grid(self, db, region: Region) -> None:
        """Smoothing models need a regular grid; the gap is filled, not faked."""
        add_event(db, region, 5, 40.0)
        add_event(db, region, 1, 60.0)
        rebuild_history(db)

        values, dates = get_region_series(db, region.code, days=30)
        assert len(values) == len(dates) == 5
        assert values[0] == pytest.approx(40.0)
        assert values[-1] == pytest.approx(60.0)
        assert all((dates[i + 1] - dates[i]).days == 1 for i in range(len(dates) - 1))

    def test_unknown_region_returns_empty(self, db) -> None:
        assert get_region_series(db, "nowhere") == ([], [])


class TestSummaryCounts:
    def test_counts_reflect_stored_rows(self, db, region: Region) -> None:
        add_event(db, region, 1, 50.0)
        counts = summary_counts(db)
        assert counts["total_events"] == 1
        assert counts["observations"] == 1
        assert counts["contains_simulated_data"] is False
