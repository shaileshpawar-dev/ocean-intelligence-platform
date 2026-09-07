"""Forecast orchestration.

Selects a model, runs it against a region's history, and -- importantly --
reports whether it beat the naive baseline. A forecast that loses to
last-value-carried-forward is reported as such rather than presented as
insight.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.forecasting.base import ForecastKind, ForecastResult, ForecastStatus
from app.forecasting.baseline import (
    HoltLinearForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
)
from app.models.enums import Severity
from app.services.analytics_service import get_region_series

logger = get_logger(__name__)

MODELS = {
    "naive": NaiveForecaster,
    "moving_average": MovingAverageForecaster,
    "holt": HoltLinearForecaster,
}

DEFAULT_MODEL = "holt"

FORWARD_FILL_CAVEAT = (
    "Days with no satellite coverage were forward-filled to build a regular "
    "daily grid. A flat stretch may reflect a revisit gap rather than stable "
    "conditions."
)
SCOPE_CAVEAT = (
    "This forecasts the platform's own detection activity for the region, not "
    "the physical movement of a pollutant. Dispersion forecasting requires "
    "current, wind and wave fields that this system does not ingest."
)


def forecast_region(
    db: Session,
    region_code: str,
    horizon: int = 7,
    model: str = DEFAULT_MODEL,
    history_days: int = 60,
) -> ForecastResult:
    """Forecast daily mean risk for one region.

    Args:
        db: Active session.
        region_code: Region cell code, e.g. ``arabian_sea_nw``.
        horizon: Days ahead to forecast.
        model: One of :data:`MODELS`.
        history_days: How much history to fit on.

    Returns:
        A :class:`ForecastResult`; ``status`` is ``INSUFFICIENT_DATA`` when
        the region has too little history, never a fabricated curve.
    """
    forecaster = MODELS.get(model, MODELS[DEFAULT_MODEL])()
    values, dates = get_region_series(db, region_code, history_days)

    if not values:
        return ForecastResult(
            model_name=forecaster.name,
            forecast_kind=ForecastKind.DETECTION_ACTIVITY,
            status=ForecastStatus.INSUFFICIENT_DATA,
            n_observations=0,
            message=f"No stored history for region {region_code!r}.",
            caveats=[SCOPE_CAVEAT],
        )

    start = (dates[-1] if dates else datetime.now(UTC).date()) + timedelta(days=1)
    result = forecaster.forecast(values, horizon, start)
    result.caveats.append(SCOPE_CAVEAT)
    if len(dates) > 1 and (dates[-1] - dates[0]).days + 1 > len(set(dates)):
        result.caveats.append(FORWARD_FILL_CAVEAT)
    else:
        result.caveats.append(FORWARD_FILL_CAVEAT)

    if result.beats_naive is False:
        result.message += (
            " This model did not beat the naive last-value baseline in "
            "backtesting; treat the trend as weakly supported."
        )
    return result


def forecast_to_severity_bands(result: ForecastResult) -> list[dict]:
    """Convert forecast risk values to severity bands with interval bounds.

    Produces the day-by-day HIGH / MEDIUM view the dashboard shows, while
    keeping the numeric interval so the band is never mistaken for certainty.
    """
    bands: list[dict] = []
    for point in result.points:
        bands.append(
            {
                "date": point.target_date.isoformat(),
                "horizon_days": point.horizon_days,
                "risk": round(point.value, 1),
                "severity": str(Severity.from_score(point.value)),
                "lower": round(point.lower, 1),
                "upper": round(point.upper, 1),
                "severity_lower": str(Severity.from_score(point.lower)),
                "severity_upper": str(Severity.from_score(point.upper)),
                "interval_confidence": point.interval_confidence,
            }
        )
    return bands


def available_models() -> list[dict]:
    """Describe the registered forecasting models."""
    return [
        {
            "key": key,
            "name": cls.name,
            "min_observations": cls.min_observations,
        }
        for key, cls in MODELS.items()
    ]


def _today() -> date:
    return datetime.now(UTC).date()
