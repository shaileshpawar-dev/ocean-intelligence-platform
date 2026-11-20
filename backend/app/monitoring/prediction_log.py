"""The one place a :class:`PredictionLog` row is written.

Latency statistics and drift detection both read this table, so anything that
runs a detector has to record it the same way or the two disagree. This used to
live as a private helper inside the satellite route, which meant it was only
reachable from one endpoint and hardcoded both the timestamp and the endpoint
label.

A failed write is logged and swallowed. Monitoring must not be able to fail an
inference that already succeeded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import PredictionLog

logger = get_logger(__name__)

#: What the live detect endpoint records. Batch replays pass their own, so a
#: reader can tell a real API call from a backfill.
DEFAULT_ENDPOINT = "POST /api/v1/detect"


def log_prediction(
    db: Session,
    *,
    request_id: str,
    detector_name: str,
    version: str,
    latency_ms: float,
    detections: list,
    error: str | None = None,
    endpoint: str = DEFAULT_ENDPOINT,
    created_at: datetime | None = None,
    input_stats: dict[str, Any] | None = None,
    commit: bool = True,
) -> bool:
    """Persist one inference record. Returns whether the row was written.

    Args:
        db: Active session.
        request_id: Caller's identifier for this inference.
        detector_name: Detector that produced ``detections``.
        version: Detector version, recorded alongside the name so a later
            reader can tell which weights produced the numbers.
        latency_ms: Measured wall-clock inference time.
        detections: Whatever the detector returned; confidences and class
            labels are summarised out of it.
        error: Failure message, or None on success.
        endpoint: Label for where the call came from.
        created_at: Defaults to now. A batch replay may pass its own, in which
            case it is responsible for saying so in ``input_stats``.
        input_stats: Coarse input description, kept instead of the image.
        commit: Set False to batch many rows into one transaction.
    """
    confidences = [d.confidence for d in detections]
    try:
        db.add(
            PredictionLog(
                request_id=request_id,
                created_at=created_at or datetime.now(UTC),
                model_name=detector_name,
                model_version=version,
                endpoint=endpoint,
                latency_ms=latency_ms,
                detection_count=len(detections),
                max_confidence=max(confidences) if confidences else None,
                mean_confidence=(
                    sum(confidences) / len(confidences) if confidences else None
                ),
                predicted_classes=[str(d.signature) for d in detections],
                input_stats=input_stats,
                success=error is None,
                error=error,
            )
        )
        if commit:
            db.commit()
        return True
    except Exception:
        db.rollback()
        logger.warning("prediction_log_failed", exc_info=True)
        return False
