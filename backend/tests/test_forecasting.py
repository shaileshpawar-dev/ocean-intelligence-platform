"""Tests for the forecasting layer.

The behaviour that matters most is the refusal path: too little history must
produce an explicit ``INSUFFICIENT_DATA`` status, never an extrapolated curve.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.forecasting.base import ForecastKind, ForecastStatus
from app.forecasting.baseline import (
    HoltLinearForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    naive_backtest_mae,
    trend_slope,
)

START = date(2026, 1, 1)


class TestInsufficientData:
    @pytest.mark.parametrize(
        "forecaster",
        [NaiveForecaster(), MovingAverageForecaster(), HoltLinearForecaster()],
    )
    def test_empty_series_refuses(self, forecaster) -> None:
        result = forecaster.forecast([], horizon=7, start_date=START)
        assert result.status is ForecastStatus.INSUFFICIENT_DATA
        assert result.points == []

    def test_holt_refuses_below_minimum(self) -> None:
        """Fitting a trend to four points is not forecasting, it is guessing."""
        result = HoltLinearForecaster().forecast(
            [10.0, 11.0, 12.0, 13.0], horizon=7, start_date=START
        )
        assert result.status is ForecastStatus.INSUFFICIENT_DATA
        assert "at least 7" in result.message

    def test_refusal_message_states_what_was_needed(self) -> None:
        result = HoltLinearForecaster().forecast([1.0], horizon=3, start_date=START)
        assert "have 1" in result.message


class TestForecastShape:
    @pytest.fixture
    def series(self) -> list[float]:
        return [50.0, 52.0, 51.0, 54.0, 56.0, 55.0, 58.0, 60.0, 59.0, 62.0]

    @pytest.mark.parametrize("horizon", [1, 7, 14])
    def test_produces_requested_horizon(self, series: list[float], horizon: int) -> None:
        result = HoltLinearForecaster().forecast(series, horizon, START)
        assert result.status is ForecastStatus.OK
        assert len(result.points) == horizon
        assert [p.horizon_days for p in result.points] == list(range(1, horizon + 1))

    def test_dates_are_consecutive_from_start(self, series: list[float]) -> None:
        result = HoltLinearForecaster().forecast(series, 5, START)
        assert result.points[0].target_date == START
        deltas = {
            (result.points[i + 1].target_date - result.points[i].target_date).days
            for i in range(len(result.points) - 1)
        }
        assert deltas == {1}

    def test_forecast_kind_is_activity_never_dispersion(
        self, series: list[float]
    ) -> None:
        """The scope boundary must be machine-readable on every result."""
        result = HoltLinearForecaster().forecast(series, 7, START)
        assert result.forecast_kind is ForecastKind.DETECTION_ACTIVITY


class TestPredictionIntervals:
    @pytest.fixture
    def series(self) -> list[float]:
        return [50.0, 52.0, 51.0, 54.0, 56.0, 55.0, 58.0, 60.0, 59.0, 62.0]

    def test_interval_contains_point_estimate(self, series: list[float]) -> None:
        result = HoltLinearForecaster().forecast(series, 7, START)
        for point in result.points:
            assert point.lower <= point.value <= point.upper

    def test_interval_widens_with_horizon(self, series: list[float]) -> None:
        """Uncertainty must grow further out, never shrink."""
        result = HoltLinearForecaster().forecast(series, 10, START)
        widths = [p.upper - p.lower for p in result.points]
        assert widths == sorted(widths)
        assert widths[-1] > widths[0]

    def test_intervals_carry_a_caveat_about_their_assumptions(
        self, series: list[float]
    ) -> None:
        result = HoltLinearForecaster().forecast(series, 7, START)
        assert any("approximation" in c.lower() for c in result.caveats)


class TestTrendBehaviour:
    def test_rising_series_forecasts_upward(self) -> None:
        rising = [float(10 + 2 * i) for i in range(14)]
        result = HoltLinearForecaster().forecast(rising, 5, START)
        assert result.points[-1].value > rising[-1]

    def test_falling_series_forecasts_downward(self) -> None:
        falling = [float(50 - 2 * i) for i in range(14)]
        result = HoltLinearForecaster().forecast(falling, 5, START)
        assert result.points[-1].value < falling[-1]

    def test_damping_prevents_runaway_extrapolation(self) -> None:
        """A steep trend must not extrapolate without bound."""
        steep = [float(10 * i) for i in range(14)]
        result = HoltLinearForecaster().forecast(steep, 30, START)
        undamped = steep[-1] + 10 * 30
        assert result.points[-1].value < undamped

    def test_flat_series_forecasts_flat(self) -> None:
        flat = [42.0] * 14
        result = HoltLinearForecaster().forecast(flat, 5, START)
        for point in result.points:
            assert point.value == pytest.approx(42.0, abs=0.5)


class TestBaselineComparison:
    def test_naive_reports_its_own_mae_as_the_baseline(self) -> None:
        series = [50.0, 52.0, 51.0, 54.0, 56.0, 55.0, 58.0]
        result = NaiveForecaster().forecast(series, 3, START)
        assert result.backtest_mae == result.naive_mae

    def test_beats_naive_is_none_without_a_backtest(self) -> None:
        result = HoltLinearForecaster().forecast([], 3, START)
        assert result.beats_naive is None

    def test_beats_naive_is_reported_honestly(self) -> None:
        """A model that loses to the baseline must say so."""
        noisy = [50.0, 90.0, 10.0, 85.0, 15.0, 95.0, 5.0, 80.0, 20.0, 88.0]
        result = HoltLinearForecaster().forecast(noisy, 3, START)
        assert result.beats_naive is not None
        assert result.beats_naive == (result.backtest_mae < result.naive_mae)

    def test_naive_mae_matches_helper(self) -> None:
        series = [10.0, 12.0, 11.0, 15.0]
        assert naive_backtest_mae(series) == pytest.approx((2 + 1 + 4) / 3)


class TestTrendSlope:
    def test_positive_slope_for_rising_series(self) -> None:
        assert trend_slope([1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.0)

    def test_negative_slope_for_falling_series(self) -> None:
        assert trend_slope([4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)

    def test_zero_slope_for_flat_series(self) -> None:
        assert trend_slope([5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_none_for_too_few_points(self) -> None:
        assert trend_slope([1.0, 2.0]) is None
