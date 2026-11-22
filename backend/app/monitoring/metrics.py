"""Operational metrics computed from the prediction log.

Everything here is measured from persisted rows. When there are no rows, the
functions return nulls and a count of zero rather than plausible defaults.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PredictionLog


def _window_start(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def latency_summary(db: Session, days: int = 7, model: str | None = None) -> dict:
    """Latency percentiles over the window, or nulls when there is no data.

    Reports **which models the figures cover**. Without that, a window holding
    two detectors produces one percentile over both, and a 9 ms screener
    averaged with a 900 ms detector gives a number that describes neither.
    ``models`` names them and ``model_label`` says ``"mixed"`` when there is
    more than one, so the card can never imply a single model it is not
    measuring.

    Args:
        db: Active session.
        days: Window length.
        model: Restrict to one model name. None measures everything logged.
    """
    conditions = [
        PredictionLog.created_at >= _window_start(days),
        PredictionLog.success.is_(True),
    ]
    if model is not None:
        conditions.append(PredictionLog.model_name == model)

    rows = db.execute(
        select(PredictionLog.latency_ms, PredictionLog.model_name).where(*conditions)
    ).all()

    if not rows:
        return {
            "n": 0,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
            "models": [],
            "model_label": None,
            "detail": "No successful predictions logged in this window.",
        }

    values = sorted(float(latency) for latency, _ in rows)
    models = sorted({name for _, name in rows})
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values), 2),
        "p50_ms": round(_percentile(values, 0.50), 2),
        "p95_ms": round(_percentile(values, 0.95), 2),
        "max_ms": round(values[-1], 2),
        "models": models,
        "model_label": models[0] if len(models) == 1 else "mixed",
    }


def prediction_volume(db: Session, days: int = 7) -> dict:
    """Counts, success rate and class mix over the window."""
    start = _window_start(days)
    total = (
        db.scalar(
            select(func.count(PredictionLog.id)).where(PredictionLog.created_at >= start)
        )
        or 0
    )
    failures = (
        db.scalar(
            select(func.count(PredictionLog.id)).where(
                PredictionLog.created_at >= start,
                PredictionLog.success.is_(False),
            )
        )
        or 0
    )

    class_rows = db.scalars(
        select(PredictionLog.predicted_classes).where(PredictionLog.created_at >= start)
    ).all()
    counter: Counter[str] = Counter()
    for classes in class_rows:
        counter.update(classes or [])

    return {
        "total_requests": total,
        "failed_requests": failures,
        "success_rate": round((total - failures) / total, 4) if total else None,
        "class_distribution": dict(counter.most_common()),
    }


def confidence_distribution(
    db: Session, start: datetime, end: datetime | None = None
) -> list[float]:
    """Mean-confidence values for predictions in a window, for drift checks."""
    stmt = select(PredictionLog.mean_confidence).where(
        PredictionLog.created_at >= start,
        PredictionLog.mean_confidence.is_not(None),
    )
    if end is not None:
        stmt = stmt.where(PredictionLog.created_at < end)
    return [float(v) for v in db.scalars(stmt).all()]


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile of a pre-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
