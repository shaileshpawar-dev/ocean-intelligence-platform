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
from app.services.analytics_service import (
    INDEX_SERIES,
    get_region_index_series,
    get_region_series,
)

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


#: Said on every index forecast. The thing being projected is a measured
#: water property, which is a different claim from projecting detections.
INDEX_SCOPE_CAVEAT = (
    "This projects a measured Sentinel-2 index for the region, not a "
    "pollutant concentration and not a detection count. The index is a band "
    "ratio: it tracks a water property, and what causes that property to "
    "change is outside what this forecast can say."
)

#: Sentinel-2 revisits every few days, so an index series is mostly carried
#: forward. Worth stating more sharply than for detection activity.
INDEX_SPARSITY_CAVEAT = (
    "Sentinel-2 revisits every few days and cloud removes more, so most days "
    "in the fitted grid are carried forward from the last clear acquisition "
    "rather than measured. The real sampling rate is given as "
    "'acquisitions' below."
)


def forecast_region_index(
    db: Session,
    region_code: str,
    index: str,
    horizon: int = 7,
    model: str = DEFAULT_MODEL,
    history_days: int = 365,
) -> ForecastResult:
    """Forecast one measured Sentinel-2 index for one region.

    Same forecaster and same backtest as the detection-activity forecast --
    including ``beats_naive``, which is the point. A projection of real
    measurements that loses to last-value-carried-forward should say so just
    as loudly as one of synthetic counts.

    ``status`` is ``INSUFFICIENT_DATA`` when the region has too few clear
    acquisitions, never a fabricated curve.
    """
    spec = INDEX_SERIES.get(index.lower())
    if spec is None:
        return ForecastResult(
            model_name=DEFAULT_MODEL,
            forecast_kind=ForecastKind.DETECTION_ACTIVITY,
            status=ForecastStatus.INSUFFICIENT_DATA,
            n_observations=0,
            message=(
                f"Unknown index {index!r}. Available: "
                f"{', '.join(sorted(INDEX_SERIES))}."
            ),
            caveats=[],
        )

    forecaster = MODELS.get(model, MODELS[DEFAULT_MODEL])()
    values, dates = get_region_index_series(db, region_code, index, history_days)

    if not values:
        return ForecastResult(
            model_name=forecaster.name,
            forecast_kind=ForecastKind.DETECTION_ACTIVITY,
            status=ForecastStatus.INSUFFICIENT_DATA,
            n_observations=0,
            message=(
                f"No stored {spec['label']} history for region "
                f"{region_code!r}. Nothing is projected."
            ),
            caveats=[INDEX_SCOPE_CAVEAT],
        )

    start = dates[-1] + timedelta(days=1)
    result = forecaster.forecast(values, horizon, start)
    result.caveats.append(INDEX_SCOPE_CAVEAT)
    result.caveats.append(INDEX_SPARSITY_CAVEAT)
    if result.beats_naive is False:
        result.message += (
            " This model did not beat the naive last-value baseline in "
            "backtesting; treat the trend as weakly supported."
        )
    return result
