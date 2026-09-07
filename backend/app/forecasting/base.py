"""Forecasting interfaces and result types.

Scope boundary (important)
--------------------------
This package forecasts **pollution detection activity** -- how the platform's
own risk and event counts for a region are trending. That is a time-series
problem over data the platform actually owns, and it is what the original
``/predict-spread`` endpoint pretended to do with hardcoded constants labelled
"LSTM-mock".

It does **not** predict physical oil-spill trajectories. Dispersion modelling
requires surface currents, wind fields, wave spectra, oil type and weathering
state, integrated in a Lagrangian transport model (GNOME, OpenDrift, MEDSLIK).
None of those inputs exist in this system. A model that outputs a plausible
"spread_km2" without them is a random number with a unit attached.

:class:`ForecastResult` therefore carries ``forecast_kind`` so a consumer can
never confuse the two.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum


class ForecastKind(StrEnum):
    """What a forecast is a forecast *of*."""

    DETECTION_ACTIVITY = "detection_activity"
    """Trend in the platform's own detections/risk. Supported."""

    PHYSICAL_DISPERSION = "physical_dispersion"
    """Physical transport of a pollutant. NOT implemented -- see module docstring."""


class ForecastStatus(StrEnum):
    """Whether a forecast could be produced at all."""

    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_SUPPORTED = "not_supported"


@dataclass(slots=True)
class ForecastPoint:
    """One forecast step with a prediction interval."""

    target_date: date
    horizon_days: int
    value: float
    lower: float
    upper: float
    interval_confidence: float = 0.80

    def to_dict(self) -> dict:
        """Serialise one forecast step, rounding floats for transport."""
        d = asdict(self)
        d["target_date"] = self.target_date.isoformat()
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


@dataclass(slots=True)
class ForecastResult:
    """A forecast plus everything needed to judge it."""

    model_name: str
    forecast_kind: ForecastKind
    status: ForecastStatus
    points: list[ForecastPoint] = field(default_factory=list)

    #: Number of historical observations the fit used.
    n_observations: int = 0
    #: Backtested one-step mean absolute error, when computable. This is the
    #: honest measure of whether the forecast is worth anything.
    backtest_mae: float | None = None
    #: MAE of the naive (last-value) baseline over the same backtest.
    #: A model that does not beat this is not adding information.
    naive_mae: float | None = None
    message: str = ""
    caveats: list[str] = field(default_factory=list)

    @property
    def beats_naive(self) -> bool | None:
        """Whether the model outperformed the naive baseline in backtesting."""
        if self.backtest_mae is None or self.naive_mae is None:
            return None
        return self.backtest_mae < self.naive_mae

    def to_dict(self) -> dict:
        """Serialise the forecast with its backtest evidence."""
        return {
            "model_name": self.model_name,
            "forecast_kind": str(self.forecast_kind),
            "status": str(self.status),
            "points": [p.to_dict() for p in self.points],
            "n_observations": self.n_observations,
            "backtest_mae": (
                round(self.backtest_mae, 3) if self.backtest_mae is not None else None
            ),
            "naive_mae": (
                round(self.naive_mae, 3) if self.naive_mae is not None else None
            ),
            "beats_naive": self.beats_naive,
            "message": self.message,
            "caveats": self.caveats,
        }


class BaseForecaster(ABC):
    """Interface for every forecasting model."""

    name: str = "base"
    #: Below this many observations the model refuses to forecast rather than
    #: extrapolating from noise.
    min_observations: int = 7

    @abstractmethod
    def forecast(
        self, series: list[float], horizon: int, start_date: date
    ) -> ForecastResult:
        """Produce ``horizon`` daily-step forecasts from a historical series.

        Args:
            series: Chronologically ordered values, one per day, no gaps.
            horizon: Number of days ahead to forecast.
            start_date: The date of the first forecast point.
        """
