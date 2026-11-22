r"""Register the evaluated SAR oil-slick screeners in the model registry.

Three SAR models have been evaluated against held-out Sentinel-1 test splits
and their results written to ``data/models/sar/*/eval_metrics.json``. None of
them was in ``model_versions``, so the Model Performance page reported zero
evaluated models while three evaluated models sat in the repository.

This script copies those measured numbers into the registry. It invents
nothing: every value written here is read from one of the three JSON files,
and anything the files do not contain is left NULL.

Usage::

    python scripts/register_sar_models.py            # write
    python scripts/register_sar_models.py --dry-run  # print, write nothing

Idempotent: rows are matched on (name, version) and updated in place, so
running it twice leaves the same three rows.

Two deliberate omissions
------------------------
``map50``, ``map50_95`` and ``iou`` stay NULL. They are object-detection
metrics and these three models are binary scene classifiers -- they emit
P(oil) for a 224x224 patch, not boxes. A null here means "this metric does not
apply", which is the honest entry; filling it with an accuracy figure dressed
up as mAP would be worse than leaving it empty.

``FPR``, the confusion matrix, the test-set size and the baseline comparison
have no columns in ``model_versions``. Rather than add a migration two days
before a demo, they go into ``notes`` verbatim, and the full structured
breakdown reaches the UI through ``GET /api/v1/models/detectors``, whose
``describe()`` already carries ``test_metrics`` and ``baseline_comparison``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.models import ModelStatus, ModelVersion  # noqa: E402

#: Where each model's evaluation lives, and the identity it is registered under.
#:
#: ``version`` matches what the detector's own ``describe()`` reports for v2 and
#: v2.2, so the registry row and the running detector agree. The expanded v2.1
#: model is not exposed as a detector, so its label follows the same scheme.
MODELS: list[dict[str, Any]] = [
    {
        "path": "data/models/sar/v2/eval_metrics.json",
        "name": "sar-oil-slick-v2",
        "version": "2.0.0-experimental",
        "checkpoint": "data/models/sar/v2/best.pt",
        "architecture": "SAROilSlickCNN",
        # Superseded by v2.1 and v2.2 on the same benchmark lineage.
        "status": ModelStatus.ARCHIVED,
    },
    {
        "path": "data/models/sar/v2_expanded/eval_metrics.json",
        "name": "sar-oil-slick-v2.1-expanded",
        "version": "2.1.0-experimental",
        "checkpoint": "data/models/sar/v2_expanded/best.pt",
        "architecture": "SAROilSlickMultiScaleCNN",
        "status": ModelStatus.ARCHIVED,
    },
    {
        "path": "data/models/sar/v2_2_scene_clean/eval_metrics.json",
        "name": "sar-oil-slick-v2.2",
        "version": "2.2.0-experimental",
        "checkpoint": "data/models/sar/v2_2_scene_clean/best.pt",
        "architecture": "SAROilSlickMultiScaleCNN",
        # The current experimental candidate screener. sar-detector-v1 remains
        # the deployed baseline, so this is staging rather than production.
        "status": ModelStatus.STAGING,
    },
]

CLASS_NAMES = ["oil_like_signature", "lookalike_or_clean_sea"]


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first key present, or None.

    The three files were written at different times and do not agree on
    spelling: v2 and v2.1 use ``precision``/``f1_score``, v2.2 uses
    ``Precision``/``F1``. Normalising here keeps that mess out of the registry.
    """
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _latency_ms(doc: dict[str, Any], metrics: dict[str, Any]) -> float | None:
    """Mean CPU latency, wherever this particular file chose to put it."""
    inline = _first(metrics, "avg_cpu_latency_ms")
    if inline is not None:
        return float(inline)
    # v2.2 keeps a fuller benchmark in its own block.
    bench = doc.get("latency_benchmark_ms") or {}
    total = bench.get("total") or {}
    mean = total.get("mean")
    return float(mean) if mean is not None else None


def _baselines(doc: dict[str, Any]) -> dict[str, Any]:
    """The baseline comparison, under whichever key this file used."""
    for key in ("baseline_comparison", "comparison_on_same_test"):
        block = doc.get(key)
        if isinstance(block, dict) and block:
            return block
    return {}


def _notes(doc: dict[str, Any], metrics: dict[str, Any], spec: dict[str, Any]) -> str:
    """Human-readable record of everything the schema has no column for."""
    tp = _first(metrics, "true_positives", "TP")
    fp = _first(metrics, "false_positives", "FP")
    tn = _first(metrics, "true_negatives", "TN")
    fn = _first(metrics, "false_negatives", "FN")
    n = _first(metrics, "test_samples") or doc.get("test_samples")
    fpr = _first(metrics, "false_positive_rate", "FPR")
    fnr = _first(metrics, "false_negative_rate", "FNR")
    accuracy = _first(metrics, "accuracy", "Accuracy")
    p95 = _first(metrics, "p95_cpu_latency_ms")
    if p95 is None:
        p95 = ((doc.get("latency_benchmark_ms") or {}).get("total") or {}).get("p95")

    lines = [
        f"{spec['architecture']} binary scene classifier on Sentinel-1 C-SAR GRD "
        f"(VV amplitude), 224x224 px input.",
        f"Dataset: {doc.get('dataset', 'PANGAEA 980773 / DARTIS 2019')} (CC BY 4.0).",
    ]
    if doc.get("test_leakage_free"):
        lines.append(
            "Test split is leakage-free: zero patch, scene or connected-component "
            "overlap with training."
        )
    if n is not None:
        lines.append(f"Test set: {n} samples.")
    if None not in (tp, fp, tn, fn):
        lines.append(f"Confusion matrix: TP={tp} FP={fp} TN={tn} FN={fn}.")
    rates = []
    if accuracy is not None:
        rates.append(f"accuracy={accuracy}")
    if fpr is not None:
        rates.append(f"FPR={fpr}")
    if fnr is not None:
        rates.append(f"FNR={fnr}")
    if rates:
        lines.append("Rates: " + ", ".join(rates) + ".")
    if p95 is not None:
        lines.append(f"p95 CPU latency: {round(float(p95), 2)} ms.")

    baselines = _baselines(doc)
    if baselines:
        parts = []
        for label, block in baselines.items():
            if not isinstance(block, dict):
                continue
            f1 = _first(block, "f1_score", "F1", "f1")
            if f1 is not None:
                parts.append(f"{label} F1={f1}")
        if parts:
            lines.append("Baseline comparison on the same test set: " + "; ".join(parts) + ".")

    lines.append(
        "mAP/IoU are null because this is a scene classifier, not an object "
        "detector; those metrics do not apply."
    )
    return " ".join(lines)


def build_row(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Read one eval_metrics.json and shape it into registry columns."""
    path = REPO_ROOT / spec["path"]
    if not path.exists():
        print(f"  SKIP {spec['name']}: {spec['path']} not found")
        return None

    doc = json.loads(path.read_text(encoding="utf-8"))
    metrics = doc.get("test_metrics") or {}
    if not metrics:
        print(f"  SKIP {spec['name']}: file has no test_metrics block")
        return None

    hyperparameters: dict[str, Any] = {}
    for key in ("decision_threshold", "param_count", "training_samples", "validation_samples"):
        if doc.get(key) is not None:
            hyperparameters[key] = doc[key]
    hyperparameters["architecture"] = spec["architecture"]

    return {
        "name": spec["name"],
        "version": spec["version"],
        "task": "detection",
        "framework": "pytorch",
        "dataset_version": doc.get("dataset", "PANGAEA 980773 / DARTIS 2019"),
        "artifact_uri": spec["checkpoint"],
        "status": str(spec["status"]),
        "is_deployed": False,
        # Measured, from the file. Nothing derived, nothing rounded up.
        "precision": _first(metrics, "precision", "Precision"),
        "recall": _first(metrics, "recall", "Recall"),
        "f1": _first(metrics, "f1_score", "F1"),
        "mean_latency_ms": _latency_ms(doc, metrics),
        # Object-detection metrics: not applicable to a scene classifier.
        "map50": None,
        "map50_95": None,
        "iou": None,
        "hyperparameters": hyperparameters or None,
        "class_names": CLASS_NAMES,
        "notes": _notes(doc, metrics, spec),
        "metrics_source": spec["path"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be written and exit without touching the database",
    )
    args = parser.parse_args()

    rows = [row for spec in MODELS if (row := build_row(spec)) is not None]
    if not rows:
        print("Nothing to register.")
        return 1

    for row in rows:
        print(
            f"  {row['name']:<30} {row['version']:<20} "
            f"P={row['precision']} R={row['recall']} F1={row['f1']} "
            f"latency={row['mean_latency_ms']}"
        )

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    created = updated = 0
    with SessionLocal() as db:
        for row in rows:
            existing = (
                db.query(ModelVersion)
                .filter_by(name=row["name"], version=row["version"])
                .one_or_none()
            )
            if existing is None:
                db.add(ModelVersion(**row))
                created += 1
            else:
                for key, value in row.items():
                    setattr(existing, key, value)
                updated += 1
        db.commit()

    print(f"\nRegistered: {created} created, {updated} updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
