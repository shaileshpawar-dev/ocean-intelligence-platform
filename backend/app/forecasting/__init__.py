"""Time-series forecasting of detection activity."""

from app.forecasting.base import (
    BaseForecaster,
    ForecastKind,
    ForecastResult,
    ForecastStatus,
)
from app.forecasting.baseline import (
    HoltLinearForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    trend_slope,
)

__all__ = [
    "BaseForecaster",
    "ForecastKind",
    "ForecastResult",
    "ForecastStatus",
    "HoltLinearForecaster",
    "MovingAverageForecaster",
    "NaiveForecaster",
    "trend_slope",
]
