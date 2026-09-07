"""Baseline forecasters.

Deliberately starts with the simplest defensible models. A naive baseline that
is honestly evaluated is worth more than an LSTM fitted to thirty points, and
every model here is backtested against the naive baseline so the API can state
whether the fancier model actually helps.

Progression documented in ``docs/forecasting.md``:
    naive -> moving average -> Holt linear -> (LSTM / PatchTST once enough
    real history has accumulated to justify them)
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from app.forecasting.base import (
    BaseForecaster,
    ForecastKind,
    ForecastPoint,
    ForecastResult,
    ForecastStatus,
)

#: z-score for an 80% two-sided interval under a normal approximation.
Z_80 = 1.2816

INTERVAL_CAVEAT = (
    "Prediction intervals assume normally distributed, homoscedastic one-step "
    "residuals and widen with the square root of the horizon. They are an "
    "approximation, not exact state-space intervals."
)
SHORT_HISTORY_CAVEAT = (
    "Fitted on a short history. Treat the trend direction as indicative and "
    "the point values as weakly supported."
)


def _insufficient(model_name: str, n: int, needed: int) -> ForecastResult:
    """Return an explicit refusal rather than a fabricated forecast."""
    return ForecastResult(
        model_name=model_name,
        forecast_kind=ForecastKind.DETECTION_ACTIVITY,
        status=ForecastStatus.INSUFFICIENT_DATA,
        n_observations=n,
        message=(
            f"Need at least {needed} daily observations to fit {model_name}; "
            f"have {n}. No forecast produced."
        ),
    )


def _residual_sigma(residuals: list[float]) -> float:
    """Standard deviation of one-step residuals, guarded for tiny samples."""
    if len(residuals) < 2:
        return 0.0
    return statistics.stdev(residuals)


def naive_backtest_mae(series: list[float]) -> float | None:
    """One-step MAE of predicting "tomorrow equals today"."""
    if len(series) < 2:
        return None
    errors = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    return sum(errors) / len(errors)


class NaiveForecaster(BaseForecaster):
    """Last observed value, carried forward. The baseline to beat."""

    name = "naive-last-value"
    min_observations = 2

    def forecast(
        self, series: list[float], horizon: int, start_date: date
    ) -> ForecastResult:
        """Fit the model and project ``horizon`` days ahead."""
        if len(series) < self.min_observations:
            return _insufficient(self.name, len(series), self.min_observations)

        last = series[-1]
        residuals = [series[i] - series[i - 1] for i in range(1, len(series))]
        sigma = _residual_sigma(residuals)
        naive_mae = naive_backtest_mae(series)

        points = [
            ForecastPoint(
                target_date=start_date + timedelta(days=h - 1),
                horizon_days=h,
                value=last,
                lower=last - Z_80 * sigma * math.sqrt(h),
                upper=last + Z_80 * sigma * math.sqrt(h),
            )
            for h in range(1, horizon + 1)
        ]
        return ForecastResult(
            model_name=self.name,
            forecast_kind=ForecastKind.DETECTION_ACTIVITY,
            status=ForecastStatus.OK,
            points=points,
            n_observations=len(series),
            backtest_mae=naive_mae,
            naive_mae=naive_mae,
            message="Last-value baseline.",
            caveats=[INTERVAL_CAVEAT],
        )


class MovingAverageForecaster(BaseForecaster):
    """Mean of the trailing window, carried forward. Robust to spikes."""

    name = "moving-average"
    min_observations = 5

    def __init__(self, window: int = 7) -> None:
        """Set the trailing window length in days."""
        self.window = window

    def forecast(
        self, series: list[float], horizon: int, start_date: date
    ) -> ForecastResult:
        """Fit the model and project ``horizon`` days ahead."""
        if len(series) < self.min_observations:
            return _insufficient(self.name, len(series), self.min_observations)

        window = min(self.window, len(series))
        level = sum(series[-window:]) / window

        # Backtest: rolling one-step-ahead over the tail of the series.
        residuals: list[float] = []
        for i in range(window, len(series)):
            pred = sum(series[i - window : i]) / window
            residuals.append(series[i] - pred)

        sigma = _residual_sigma(residuals)
        mae = sum(abs(r) for r in residuals) / len(residuals) if residuals else None

        points = [
            ForecastPoint(
                target_date=start_date + timedelta(days=h - 1),
                horizon_days=h,
                value=level,
                lower=level - Z_80 * sigma * math.sqrt(h),
                upper=level + Z_80 * sigma * math.sqrt(h),
            )
            for h in range(1, horizon + 1)
        ]
        return ForecastResult(
            model_name=self.name,
            forecast_kind=ForecastKind.DETECTION_ACTIVITY,
            status=ForecastStatus.OK,
            points=points,
            n_observations=len(series),
            backtest_mae=mae,
            naive_mae=naive_backtest_mae(series),
            message=f"Trailing {window}-day mean.",
            caveats=[INTERVAL_CAVEAT],
        )


class HoltLinearForecaster(BaseForecaster):
    """Holt's linear exponential smoothing: level plus damped trend.

    Chosen as the primary model because pollution-activity series are short,
    noisy, non-seasonal at the daily scale, and the thing a user actually
    wants is the trend direction. The trend is damped so a week of increases
    does not extrapolate to an absurd value ten days out.
    """

    name = "holt-linear-damped"
    min_observations = 7

    def __init__(self, alpha: float = 0.4, beta: float = 0.15, phi: float = 0.90) -> None:
        """Set the smoothing, trend and damping coefficients."""
        self.alpha = alpha  # level smoothing
        self.beta = beta  # trend smoothing
        self.phi = phi  # trend damping

    def _fit(self, series: list[float]) -> tuple[float, float, list[float]]:
        """Run the recursion, returning final level, trend and residuals."""
        level = series[0]
        trend = series[1] - series[0]
        residuals: list[float] = []

        for value in series[1:]:
            forecast = level + self.phi * trend
            residuals.append(value - forecast)
            prev_level = level
            level = self.alpha * value + (1 - self.alpha) * forecast
            trend = self.beta * (level - prev_level) + (1 - self.beta) * self.phi * trend
        return level, trend, residuals

    def forecast(
        self, series: list[float], horizon: int, start_date: date
    ) -> ForecastResult:
        """Fit the model and project ``horizon`` days ahead."""
        if len(series) < self.min_observations:
            return _insufficient(self.name, len(series), self.min_observations)

        level, trend, residuals = self._fit(series)
        sigma = _residual_sigma(residuals)
        mae = sum(abs(r) for r in residuals) / len(residuals) if residuals else None

        points: list[ForecastPoint] = []
        for h in range(1, horizon + 1):
            # Damped-trend h-step forecast: sum of phi^1..phi^h times trend.
            damp_sum = sum(self.phi**i for i in range(1, h + 1))
            value = level + damp_sum * trend
            spread = Z_80 * sigma * math.sqrt(h)
            points.append(
                ForecastPoint(
                    target_date=start_date + timedelta(days=h - 1),
                    horizon_days=h,
                    value=value,
                    lower=value - spread,
                    upper=value + spread,
                )
            )

        caveats = [INTERVAL_CAVEAT]
        if len(series) < 14:
            caveats.append(SHORT_HISTORY_CAVEAT)

        return ForecastResult(
            model_name=self.name,
            forecast_kind=ForecastKind.DETECTION_ACTIVITY,
            status=ForecastStatus.OK,
            points=points,
            n_observations=len(series),
            backtest_mae=mae,
            naive_mae=naive_backtest_mae(series),
            message=(
                f"Holt linear smoothing (alpha={self.alpha}, beta={self.beta}, "
                f"damping phi={self.phi})."
            ),
            caveats=caveats,
        )


def trend_slope(series: list[float]) -> float | None:
    """Ordinary least-squares slope of ``series`` against day index.

    Returned in units of value-per-day and fed to the risk engine's
    ``historical_trend`` factor.
    """
    n = len(series)
    if n < 3:
        return None
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(series) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, series, strict=True))
    return covariance / denom
