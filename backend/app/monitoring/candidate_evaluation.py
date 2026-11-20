"""Score the SAR screener against the stored candidates' ground truth.

The ``sar_candidates`` table holds both the model's output (``raw_confidence``)
and the benchmark label it was drawn from (``subset``), so a confusion matrix
and an ROC curve can be computed from the database directly, with no new
dataset and nothing retrained.

Labels follow the PANGAEA 980773 / DARTIS subsets:

* ``ow`` -- oil, open water          -> positive
* ``oc`` -- oil, coastal             -> positive
* ``nw`` -- no oil, open water       -> negative
* ``nc`` -- no oil, coastal          -> negative

The scores are **uncalibrated**. ``raw_confidence`` is the network's output,
not a probability that survived a calibration step, so the threshold is a
ranking cut rather than a probability. Every response says so, because a
precision figure quoted off an uncalibrated score invites being read as one
that was calibrated.

AUC is threshold-independent and is the honest headline here; the confusion
matrix at a chosen threshold is a slice through it.

sklearn is not a dependency of this project and is not worth adding for two
textbook formulas, so both are computed here.
"""

from __future__ import annotations

from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sar_candidate import SARCandidate

#: Subsets that denote a true oil slick.
POSITIVE_SUBSETS = frozenset({"ow", "oc"})

#: Subsets that denote a look-alike or clean sea.
NEGATIVE_SUBSETS = frozenset({"nw", "nc"})

UNCALIBRATED_NOTE = (
    "Scores are the network's raw output and have not been calibrated, so the "
    "threshold is a ranking cut rather than a probability. AUC is "
    "threshold-independent; the confusion matrix is one slice through it."
)


def _ratio(numerator: int, denominator: int) -> float | None:
    """A rate, or None when it is undefined. Never silently zero."""
    return numerator / denominator if denominator else None


def confusion_at(
    labels: list[int], scores: list[float], threshold: float
) -> dict[str, int]:
    """Confusion matrix at one threshold. Predicted positive is ``score >= t``."""
    tp = fp = tn = fn = 0
    for label, score in zip(labels, scores, strict=True):
        predicted = score >= threshold
        if label == 1 and predicted:
            tp += 1
        elif label == 1:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def roc_curve(labels: list[int], scores: list[float]) -> list[dict[str, float]]:
    """ROC points, one per distinct score, plus the (0,0) and (1,1) anchors.

    Walks the samples in descending score order, moving up for a positive and
    right for a negative, and emits a point whenever the score changes --
    which is what keeps tied scores on a single point instead of inventing a
    staircase between them.
    """
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return []

    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    points = [{"fpr": 0.0, "tpr": 0.0, "threshold": 1.0}]
    tp = fp = 0
    previous: float | None = None

    for i in order:
        score = scores[i]
        if previous is not None and score != previous:
            points.append(
                {
                    "fpr": round(fp / negatives, 6),
                    "tpr": round(tp / positives, 6),
                    "threshold": round(previous, 6),
                }
            )
        if labels[i] == 1:
            tp += 1
        else:
            fp += 1
        previous = score

    points.append({"fpr": 1.0, "tpr": 1.0, "threshold": round(min(scores), 6)})
    return points


def auc_from(points: list[dict[str, float]]) -> float | None:
    """Area under the ROC curve, by the trapezoid rule over its own points."""
    if len(points) < 2:
        return None
    area = 0.0
    for left, right in pairwise(points):
        area += (right["fpr"] - left["fpr"]) * (right["tpr"] + left["tpr"]) / 2.0
    return round(area, 6)


def evaluate_candidates(db: Session, threshold: float = 0.5) -> dict:
    """Confusion matrix, rates, ROC and AUC over every labelled candidate."""
    rows = db.execute(
        select(
            SARCandidate.subset,
            SARCandidate.raw_confidence,
            SARCandidate.detector_name,
            SARCandidate.model_version,
            SARCandidate.confidence_is_calibrated,
        )
    ).all()

    labels: list[int] = []
    scores: list[float] = []
    models: set[str] = set()
    calibrated = False
    skipped = 0

    for subset, score, detector, version, is_calibrated in rows:
        if score is None or subset not in POSITIVE_SUBSETS | NEGATIVE_SUBSETS:
            skipped += 1
            continue
        labels.append(1 if subset in POSITIVE_SUBSETS else 0)
        scores.append(float(score))
        models.add(f"{detector}:{version}")
        calibrated = calibrated or bool(is_calibrated)

    if not labels:
        return {
            "n": 0,
            "threshold": threshold,
            "model": None,
            "detail": "No labelled candidates with a score are stored.",
            "note": UNCALIBRATED_NOTE,
        }

    matrix = confusion_at(labels, scores, threshold)
    tp, fp, tn, fn = matrix["tp"], matrix["fp"], matrix["tn"], matrix["fn"]
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall
        else None
    )
    points = roc_curve(labels, scores)

    return {
        "n": len(labels),
        "positives": sum(labels),
        "negatives": len(labels) - sum(labels),
        "skipped": skipped,
        "threshold": threshold,
        # Named so the panel cannot be mistaken for a different model's score.
        "model": sorted(models)[0] if len(models) == 1 else sorted(models),
        "scores_are_calibrated": calibrated,
        "confusion": matrix,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "fpr": round(v, 4) if (v := _ratio(fp, fp + tn)) is not None else None,
        "accuracy": round((tp + tn) / len(labels), 4),
        "roc": points,
        "auc": auc_from(points),
        "positive_subsets": sorted(POSITIVE_SUBSETS),
        "negative_subsets": sorted(NEGATIVE_SUBSETS),
        "note": UNCALIBRATED_NOTE,
    }
