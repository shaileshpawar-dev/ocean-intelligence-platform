"""Model registry, runtime detector status and drift endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ModelVersion
from app.monitoring.drift import run_drift_checks
from app.monitoring.metrics import latency_summary, prediction_volume
from app.schemas.analytics import DetectorInfoOut, ModelVersionOut
from app.vision.registry import describe_all

router = APIRouter(tags=["ml"])


@router.get(
    "/models",
    response_model=list[ModelVersionOut],
    summary="Registered model versions and their measured metrics",
)
def list_models(db: Session = Depends(get_db)) -> list[ModelVersionOut]:
    """List the model registry.

    Metrics are null until an evaluation run records them. A null mAP means
    "not measured"; it is never back-filled with a plausible-looking number.
    Populate with ``python -m ml.evaluation.evaluate_detector``.
    """
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())).all()
    return [
        ModelVersionOut(
            name=m.name,
            version=m.version,
            task=m.task,
            framework=m.framework,
            status=m.status,
            is_deployed=m.is_deployed,
            dataset_version=m.dataset_version,
            trained_at=m.trained_at.isoformat() if m.trained_at else None,
            map50=m.map50,
            map50_95=m.map50_95,
            precision=m.precision,
            recall=m.recall,
            f1=m.f1,
            iou=m.iou,
            mean_latency_ms=m.mean_latency_ms,
            class_names=m.class_names,
            metrics_source=m.metrics_source,
            notes=m.notes,
        )
        for m in rows
    ]


@router.get(
    "/models/detectors",
    response_model=list[DetectorInfoOut],
    summary="Runtime status of loaded detectors",
)
def list_detectors() -> list[DetectorInfoOut]:
    """Which detectors are actually loaded in this process, and what they may claim."""
    return [DetectorInfoOut(**d) for d in describe_all()]


@router.get(
    "/models/{name}/{version}",
    response_model=ModelVersionOut,
    summary="One registered model version",
)
def get_model(name: str, version: str, db: Session = Depends(get_db)) -> ModelVersionOut:
    """Fetch a single registry entry."""
    model = db.scalar(
        select(ModelVersion).where(
            ModelVersion.name == name, ModelVersion.version == version
        )
    )
    if model is None:
        raise HTTPException(status_code=404, detail=f"No model {name}:{version}")
    return ModelVersionOut(
        name=model.name,
        version=model.version,
        task=model.task,
        framework=model.framework,
        status=model.status,
        is_deployed=model.is_deployed,
        dataset_version=model.dataset_version,
        trained_at=model.trained_at.isoformat() if model.trained_at else None,
        map50=model.map50,
        map50_95=model.map50_95,
        precision=model.precision,
        recall=model.recall,
        f1=model.f1,
        iou=model.iou,
        mean_latency_ms=model.mean_latency_ms,
        class_names=model.class_names,
        metrics_source=model.metrics_source,
        notes=model.notes,
    )


@router.get("/metrics", summary="Operational inference metrics")
def metrics(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)) -> dict:
    """Latency and volume statistics computed from the prediction log.

    These are measured, not estimated: every ``/detect`` call writes a row.
    """
    return {
        "window_days": days,
        "latency": latency_summary(db, days),
        "volume": prediction_volume(db, days),
    }


@router.get("/drift", summary="Data and prediction drift checks")
def drift(
    baseline_days: int = Query(30, ge=7, le=180),
    current_days: int = Query(7, ge=1, le=60),
    db: Session = Depends(get_db),
) -> dict:
    """Compare a recent window of predictions against a baseline window.

    Reports ``insufficient_data`` rather than a spurious verdict when either
    window is too small. Drift never triggers automatic retraining; it raises
    a flag for human review, as described in ``docs/mlops.md``.
    """
    return run_drift_checks(db, baseline_days=baseline_days, current_days=current_days)
