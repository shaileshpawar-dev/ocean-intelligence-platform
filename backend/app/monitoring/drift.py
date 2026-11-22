"""Drift detection over prediction confidence and class distributions.

Uses the Population Stability Index, which is interpretable, cheap and does
not assume a distributional form. Conventional operating bands:

    PSI < 0.10  -> stable
    0.10-0.25   -> moderate shift, warning
    PSI > 0.25  -> significant shift, investigate

Drift **never** triggers automatic retraining here. It raises a flag for human
review. Retraining on drifted data without knowing why it drifted is how a
model gets quietly poisoned -- see ``docs/mlops.md``.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import DriftReport, DriftStatus, PredictionLog
from app.monitoring.metrics import confidence_distribution

logger = get_logger(__name__)

#: Minimum samples per window before a verdict is meaningful.
MIN_SAMPLES = 30

PSI_WARNING = 0.10
PSI_DRIFT = 0.25

#: Fixed bins over [0, 1] so baseline and current are always comparable.
CONFIDENCE_BINS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def population_stability_index(
    baseline: list[float], current: list[float], bins: list[float]
) -> float:
    """PSI between two samples over fixed bin edges.

    Empty bins are floored at a small epsilon so the logarithm stays finite;
    without that a single unseen bin sends PSI to infinity.
    """
    if not baseline or not current:
        return 0.0

    def proportions(values: list[float]) -> list[float]:
        counts = [0] * (len(bins) - 1)
        for value in values:
            for i in range(len(bins) - 1):
                upper_inclusive = i == len(bins) - 2
                if bins[i] <= value < bins[i + 1] or (
                    upper_inclusive and value == bins[-1]
                ):
                    counts[i] += 1
                    break
        total = sum(counts) or 1
        return [max(c / total, 1e-6) for c in counts]

    base_p = proportions(baseline)
    curr_p = proportions(current)
    return sum((c - b) * math.log(c / b) for b, c in zip(base_p, curr_p, strict=True))


def categorical_psi(baseline: list[str], current: list[str]) -> float:
    """PSI over a categorical distribution, using the union of categories."""
    if not baseline or not current:
        return 0.0
    base_counts, curr_counts = Counter(baseline), Counter(current)
    categories = set(base_counts) | set(curr_counts)
    base_total, curr_total = len(baseline), len(current)

    total = 0.0
    for category in categories:
        b = max(base_counts[category] / base_total, 1e-6)
        c = max(curr_counts[category] / curr_total, 1e-6)
        total += (c - b) * math.log(c / b)
    return total


def _status_for(psi: float) -> DriftStatus:
    if psi > PSI_DRIFT:
        return DriftStatus.DRIFT_DETECTED
    if psi > PSI_WARNING:
        return DriftStatus.WARNING
    return DriftStatus.OK


def run_drift_checks(db: Session, baseline_days: int = 30, current_days: int = 7) -> dict:
    """Compare a recent window against an earlier baseline window.

    The baseline is the period *preceding* the current window, so the two
    never overlap -- comparing a window against a baseline that contains it
    dilutes any real shift.
    """
    now = datetime.now(UTC)
    current_start = now - timedelta(days=current_days)
    baseline_start = current_start - timedelta(days=baseline_days)

    checks: list[dict] = []

    # -- Confidence distribution ------------------------------------------
    base_conf = confidence_distribution(db, baseline_start, current_start)
    curr_conf = confidence_distribution(db, current_start)
    checks.append(
        _build_check(
            db,
            metric="mean_confidence",
            baseline_n=len(base_conf),
            current_n=len(curr_conf),
            psi=population_stability_index(base_conf, curr_conf, CONFIDENCE_BINS),
            baseline_days=baseline_days,
            current_days=current_days,
            detail={"bins": CONFIDENCE_BINS},
        )
    )

    # -- Predicted class distribution -------------------------------------
    base_classes = _classes_between(db, baseline_start, current_start)
    curr_classes = _classes_between(db, current_start, None)
    checks.append(
        _build_check(
            db,
            metric="predicted_class_distribution",
            baseline_n=len(base_classes),
            current_n=len(curr_classes),
            psi=categorical_psi(base_classes, curr_classes),
            baseline_days=baseline_days,
            current_days=current_days,
            detail={
                "baseline": dict(Counter(base_classes)),
                "current": dict(Counter(curr_classes)),
            },
        )
    )

    db.commit()

    statuses = [c["status"] for c in checks]
    if str(DriftStatus.DRIFT_DETECTED) in statuses:
        overall = str(DriftStatus.DRIFT_DETECTED)
    elif str(DriftStatus.WARNING) in statuses:
        overall = str(DriftStatus.WARNING)
    elif all(s == str(DriftStatus.INSUFFICIENT_DATA) for s in statuses):
        overall = str(DriftStatus.INSUFFICIENT_DATA)
    else:
        overall = str(DriftStatus.OK)

    baseline_provenance = _window_provenance(db, baseline_start, current_start)
    current_provenance = _window_provenance(db, current_start, None)

    return {
        "overall_status": overall,
        "baseline_window_days": baseline_days,
        "current_window_days": current_days,
        "min_samples_required": MIN_SAMPLES,
        "thresholds": {"warning": PSI_WARNING, "drift": PSI_DRIFT},
        "checks": checks,
        # What the two windows actually hold, so the panel can say whether it
        # is comparing live traffic or a replayed benchmark.
        "provenance": {
            "baseline": baseline_provenance,
            "current": current_provenance,
            "note": _provenance_note(baseline_provenance, current_provenance),
        },
        "action": (
            "Flag for human review. This platform does not retrain "
            "automatically on drift."
        ),
    }


def _window_provenance(db: Session, start: datetime, end: datetime | None) -> dict:
    """Where a window's rows came from, read from what the rows themselves say.

    A batch replay records ``timestamp_is_synthetic`` and the benchmark
    ``split`` in ``input_stats``. Reading it back here means the panel's
    honesty label is derived rather than asserted: if the replay is ever
    removed, the label disappears with it instead of lingering as a claim
    about data that is no longer there.

    Read in Python rather than with a JSON operator because the suite runs on
    SQLite and the deployment on PostgreSQL, and a window is a hundred rows.
    """
    stmt = select(PredictionLog.input_stats, PredictionLog.mean_confidence).where(
        PredictionLog.created_at >= start
    )
    if end is not None:
        stmt = stmt.where(PredictionLog.created_at < end)

    total = 0
    replayed = 0
    # The confidence PSI only sees rows with a confidence, so a window can
    # hold more rows than the statistic was computed over. Counting both keeps
    # the sentence under the panel from contradicting the table beside it.
    scored = 0
    splits: Counter[str] = Counter()
    for stats, mean_confidence in db.execute(stmt).all():
        total += 1
        if mean_confidence is not None:
            scored += 1
        if not isinstance(stats, dict):
            continue
        if stats.get("timestamp_is_synthetic"):
            replayed += 1
            if split := stats.get("split"):
                splits[str(split)] += 1

    return {
        "n": total,
        "scored_n": scored,
        "replayed_n": replayed,
        "is_replayed": replayed > 0,
        "splits": dict(splits.most_common()),
        "dominant_split": splits.most_common(1)[0][0] if splits else None,
    }


def _provenance_note(baseline: dict, current: dict) -> str | None:
    """One sentence naming what each window actually holds, or None.

    Returns None when nothing in either window was replayed, so a live
    deployment never carries a caveat about a batch it does not contain.

    Where a window holds rows the confidence PSI could not use -- the two old
    mock-detector rows log no confidence -- both counts are given. Quoting only
    the row count made the sentence say 102 while the table beside it said 100,
    which reads as one of them being wrong rather than as two different
    questions.
    """
    if not (baseline["is_replayed"] or current["is_replayed"]):
        return None

    def describe(window: dict) -> str:
        split = window["dominant_split"] or "unlabelled batch"
        total, scored = window["n"], window["scored_n"]
        if scored == total:
            return f"{split} (n={total})"
        return f"{split} ({total} rows, {scored} with confidence)"

    return (
        f"Replayed benchmark: baseline = {describe(baseline)}, "
        f"current = {describe(current)}. Inferences are real; window "
        "timestamps are assigned, not live traffic."
    )


def _classes_between(db: Session, start: datetime, end: datetime | None) -> list[str]:
    """Flatten predicted class labels logged in a window."""
    stmt = select(PredictionLog.predicted_classes).where(
        PredictionLog.created_at >= start
    )
    if end is not None:
        stmt = stmt.where(PredictionLog.created_at < end)
    return [label for row in db.scalars(stmt).all() or [] for label in (row or [])]


def _build_check(
    db: Session,
    *,
    metric: str,
    baseline_n: int,
    current_n: int,
    psi: float,
    baseline_days: int,
    current_days: int,
    detail: dict,
) -> dict:
    """Assemble one check result and persist it."""
    if baseline_n < MIN_SAMPLES or current_n < MIN_SAMPLES:
        status = DriftStatus.INSUFFICIENT_DATA
        message = (
            f"Need at least {MIN_SAMPLES} samples per window; have "
            f"baseline={baseline_n}, current={current_n}. No verdict issued."
        )
        psi_value: float | None = None
    else:
        status = _status_for(psi)
        psi_value = round(psi, 4)
        message = f"PSI {psi_value} over {metric}."

    report = DriftReport(
        report_id=f"drift_{uuid.uuid4().hex[:12]}",
        metric=metric,
        status=str(status),
        baseline_window_days=baseline_days,
        current_window_days=current_days,
        baseline_n=baseline_n,
        current_n=current_n,
        statistic=psi_value,
        threshold=PSI_DRIFT,
        detail=detail,
    )
    db.add(report)

    return {
        "metric": metric,
        "status": str(status),
        "psi": psi_value,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "message": message,
        "detail": detail,
    }
