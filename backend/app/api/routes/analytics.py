"""Trend, forecast and risk-explanation endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import demo_mode_notes, make_provenance
from app.core.database import get_db
from app.models import Region, RiskAssessment
from app.models.pollution import PollutionEvent
from app.schemas.analytics import ForecastOut, RegionTrendOut
from app.schemas.common import ListResponse
from app.schemas.pollution import RiskAssessmentOut
from app.services import forecast_service
from app.services.analytics_service import get_trends, summary_counts

router = APIRouter(tags=["analytics"])

#: Codes that ``refinement_service`` mints for stage-2 sub-cells, as
#: ``{parent_code}__r{row}c{col}``. These regions hold no detection history of
#: their own, so they cannot be forecast.
REFINED_CELL_CODE = re.compile(r"__r\d+c\d+$")


@router.get(
    "/trends",
    response_model=ListResponse[RegionTrendOut],
    summary="Per-region activity trends",
)
def trends(
    days: int = Query(30, ge=1, le=365),
    parent_region: str | None = Query(None, description="e.g. Arabian Sea"),
    db: Session = Depends(get_db),
) -> ListResponse[RegionTrendOut]:
    """Daily risk and event-count series per region.

    ``coverage_ratio`` reports how many days of the window were actually
    observed. A low ratio means satellite revisit gaps, not calm water, and
    the dashboard renders those stretches differently.
    """
    items = [t.to_dict() for t in get_trends(db, days=days, parent_region=parent_region)]
    return ListResponse[RegionTrendOut](
        count=len(items),
        items=items,
        provenance=make_provenance(
            "zone_history",
            items,
            evidence_key="_none",
            simulated_key="contains_simulated_data",
            notes=demo_mode_notes(),
        ),
    )


@router.get(
    "/forecast/{region_code}",
    response_model=ForecastOut,
    summary="Forecast detection activity for a region",
)
def forecast(
    region_code: str,
    horizon: int = Query(7, ge=1, le=30),
    model: str = Query("holt", description="naive | moving_average | holt"),
    history_days: int = Query(60, ge=7, le=365),
    index: str | None = Query(
        None,
        description=(
            "Forecast a measured Sentinel-2 index instead of detection "
            "activity: ndci | ndti | fdi. Omit for detection activity."
        ),
    ),
    db: Session = Depends(get_db),
) -> ForecastOut:
    """Forecast a region's detection activity, or one measured index.

    Without ``index`` this forecasts the trend in this platform's own
    detections. With it, the same model and the same backtest are run over a
    **measured** Sentinel-2 series instead -- real acquisitions on real dates.

    Neither is a physical dispersion forecast: the system does not model where
    a slick will drift. ``forecast_kind`` and the caveats make the distinction
    explicit on every response.
    """
    if model not in forecast_service.MODELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown model {model!r}. Available: {sorted(forecast_service.MODELS)}"
            ),
        )
    # Checked before the region exists, because this is a statement about the
    # shape of the code rather than about one row: a stage-2 refined sub-cell
    # is never forecastable, refined or not. Detections are recorded against
    # the monitored region one level up, so a sub-cell holds no history of its
    # own and would otherwise come back as "no stored history" -- which reads
    # as a data gap rather than as the wrong code being asked for.
    #
    # The marker is the suffix refinement_service writes
    # (``{parent}__r{row}c{col}``). ``Region.parent_code`` cannot be used:
    # every region has one, and it holds a display name, not a region code.
    refined = REFINED_CELL_CODE.search(region_code)
    if refined:
        parent_code = region_code[: refined.start()]
        raise HTTPException(
            status_code=400,
            detail=(
                f"{region_code!r} is a stage-2 refined sub-cell. Detection "
                "history is aggregated at the monitored-region level, so "
                "sub-cells cannot be forecast individually. Request "
                f"/forecast/{parent_code} instead."
            ),
        )

    region = db.scalar(select(Region).where(Region.code == region_code))
    if region is None:
        raise HTTPException(status_code=404, detail=f"No region {region_code!r}")

    if index:
        # An index series is sparse (Sentinel-2 revisit plus cloud), so it
        # gets the longer default window rather than the 60 days that suit
        # daily detection counts.
        result = forecast_service.forecast_region_index(
            db,
            region_code,
            index,
            horizon=horizon,
            model=model,
            history_days=max(history_days, 365),
        )
    else:
        result = forecast_service.forecast_region(
            db, region_code, horizon=horizon, model=model, history_days=history_days
        )
    payload = result.to_dict()
    payload["region_code"] = region_code
    payload["index"] = index
    payload["bands"] = forecast_service.forecast_to_severity_bands(result)
    return ForecastOut(**payload)


@router.get(
    "/risk/{event_id}",
    response_model=RiskAssessmentOut,
    summary="Explainable risk breakdown for an event",
)
def risk(event_id: str, db: Session = Depends(get_db)) -> RiskAssessmentOut:
    """Return the per-factor point breakdown behind an event's risk score.

    The contributions sum to the score. This is what the dashboard's
    explanation panel renders -- no language model is involved in producing
    the number or the breakdown.
    """
    event = db.scalar(select(PollutionEvent).where(PollutionEvent.event_id == event_id))
    if event is None:
        raise HTTPException(status_code=404, detail=f"No event {event_id!r}")

    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.event_id == event.id)
        .order_by(RiskAssessment.created_at.desc())
    )
    if assessment is None:
        raise HTTPException(
            status_code=404, detail=f"No risk assessment stored for {event_id!r}"
        )

    return RiskAssessmentOut(
        assessment_id=assessment.assessment_id,
        score=assessment.score,
        severity=assessment.severity,
        engine_version=assessment.engine_version,
        contributions=assessment.contributions,
        missing_factors=assessment.missing_factors or [],
        narrative=assessment.narrative,
        evidence_level=assessment.evidence_level,
    )


@router.get("/overview", summary="Dashboard headline counters")
def overview(db: Session = Depends(get_db)) -> dict:
    """Aggregate counts for the overview strip."""
    counts = summary_counts(db)
    counts["notes"] = demo_mode_notes()
    return counts
