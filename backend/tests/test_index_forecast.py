"""Forecasting a measured index, and keeping the baseline honest about it.

The detection-activity forecast projects this platform's own output. This one
projects a *measurement*, which is a stronger thing to be doing and therefore
needs the same checks applied at least as strictly.

Two in particular. The series must come from the observation table rather
than the event table: events are threshold exceedances, so a series built
from them is mostly zeros and forecasting it would be forecasting the
threshold rather than the water. And readings below the water-pixel floor
must stay out, because a mean over eight pixels moves the series without
describing anything.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.models import Region
from app.models.optical import OpticalIndexObservation
from app.services.analytics_service import INDEX_SERIES, get_region_index_series
from app.services.forecast_service import forecast_region_index
from app.vision.sentinel2_indices import MIN_WATER_PIXELS


@pytest.fixture
def region(db) -> Region:
    row = Region(
        code="malabar_coast_n",
        name="Malabar Coast N",
        min_lon=74.0,
        min_lat=11.0,
        max_lon=75.5,
        max_lat=12.5,
        centroid_lat=11.75,
        centroid_lon=74.75,
    )
    db.add(row)
    db.commit()
    return row


def _seed(db, region: Region, days: list[int], ndci: float = 0.05, **overrides):
    """Readings at the given day-offsets back from a fixed recent date."""
    today = date.today()
    for offset in days:
        base = {
            "region_id": region.id,
            "observed_on": today - timedelta(days=offset),
            "ndci_mean": ndci,
            "ndci_p50": ndci,
            "ndti_mean": -0.2,
            "ndti_p50": -0.2,
            "fdi_mean": 0.01,
            "fdi_p90": 0.02,
            "water_pixels": 5000,
            "total_pixels": 10000,
            "max_cloud_pct": 30,
            "evidence_level": "OBSERVED",
            "source": "Copernicus Sentinel-2 L2A",
        }
        db.add(OpticalIndexObservation(**{**base, **overrides}))
    db.commit()


class TestTheSeries:
    """Where the numbers come from, and what is excluded."""

    def test_it_reads_measured_observations(self, db, region):
        _seed(db, region, [12, 7, 2])

        values, dates = get_region_index_series(db, region.code, "ndci")

        assert values, "a region with acquisitions must produce a series"
        assert len(dates) == 11, "11 days between the oldest and newest"

    def test_gaps_are_forward_filled_to_a_regular_grid(self, db, region):
        """Sentinel-2 revisits every few days; the smoother needs daily."""
        _seed(db, region, [10, 0])

        values, dates = get_region_index_series(db, region.code, "ndci")

        assert len(values) == len(dates) == 11
        assert len(set(values)) == 1, "the gap carries the last value forward"

    def test_low_water_readings_are_excluded(self, db, region):
        """A mean over eight pixels would move the series describing nothing."""
        _seed(db, region, [5], water_pixels=MIN_WATER_PIXELS - 1)

        assert get_region_index_series(db, region.code, "ndci") == ([], [])

    def test_an_unknown_index_returns_nothing_rather_than_guessing(self, db, region):
        _seed(db, region, [5, 1])

        assert get_region_index_series(db, region.code, "salinity") == ([], [])

    def test_every_offered_index_maps_to_a_stored_column(self, db, region):
        """A selector option with no column behind it would 500 on click."""
        _seed(db, region, [9, 4, 0])

        for key in INDEX_SERIES:
            values, _ = get_region_index_series(db, region.code, key)
            assert values, f"{key} produced no series"


class TestTheForecast:
    """Same model, same backtest, same verdict."""

    def test_a_region_with_history_is_forecast(self, db, region):
        _seed(db, region, list(range(0, 40, 2)))

        result = forecast_region_index(db, region.code, "ndci", horizon=7)

        assert result.status == "ok"
        assert len(result.points) == 7

    def test_a_region_with_no_history_refuses_rather_than_invents(self, db, region):
        result = forecast_region_index(db, region.code, "ndci")

        assert result.status == "insufficient_data"
        assert result.points == []
        assert "Nothing is projected" in result.message

    def test_an_unknown_index_refuses_and_names_the_options(self, db, region):
        result = forecast_region_index(db, region.code, "turbulence")

        assert result.status == "insufficient_data"
        assert "ndci" in result.message

    def test_losing_to_the_naive_baseline_is_stated(self, db, region):
        """The whole point of keeping the backtest on the real series."""
        _seed(db, region, list(range(0, 40, 2)))

        result = forecast_region_index(db, region.code, "ndci", horizon=7)

        if result.beats_naive is False:
            assert "did not beat the naive" in result.message
        assert result.naive_mae is not None

    def test_it_says_it_projects_a_property_not_a_pollutant(self, db, region):
        _seed(db, region, list(range(0, 40, 2)))

        caveats = " ".join(forecast_region_index(db, region.code, "fdi").caveats)

        assert "not a pollutant concentration" in caveats
        assert "carried forward" in caveats
