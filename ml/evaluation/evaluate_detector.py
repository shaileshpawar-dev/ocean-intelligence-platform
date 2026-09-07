r"""Evaluate a detector against a labelled dataset and register the metrics.

This script is the *only* thing permitted to write metrics into the model
registry. Until it runs, a registered model reports ``null`` for mAP,
precision and recall -- which is an honest statement that it has not been
evaluated, not a bug.

Usage:
    python -m ml.evaluation.evaluate_detector \\
        --model-path /path/to/best.pt \\
        --dataset /path/to/data.yaml \\
        --dataset-version v1 \\
        --register

Without ``--register`` the report is printed and nothing is written.

Requires ``ultralytics`` and a YOLO-format dataset. Neither is a hard
dependency of the platform: this is a development-time tool.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# Make the backend package importable when run from the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.models import ModelVersion  # noqa: E402


@dataclass(slots=True)
class EvaluationReport:
    """Measured metrics for one model against one dataset version."""

    model_name: str
    model_version: str
    dataset_version: str
    evaluated_at: str
    n_images: int

    map50: float | None = None
    map50_95: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    mean_latency_ms: float | None = None
    per_class: dict | None = None

    def to_dict(self) -> dict:
        """Serialise the report."""
        return asdict(self)

    def render(self) -> str:
        """Human-readable summary for the console."""

        def fmt(value: float | None) -> str:
            return f"{value:.4f}" if value is not None else "not measured"

        latency = (
            f"{self.mean_latency_ms:.1f} ms" if self.mean_latency_ms else "not measured"
        )
        lines = [
            "=" * 62,
            "DETECTOR EVALUATION REPORT",
            "=" * 62,
            f"Model            {self.model_name}:{self.model_version}",
            f"Dataset version  {self.dataset_version}",
            f"Images           {self.n_images}",
            f"Evaluated at     {self.evaluated_at}",
            "",
            f"  mAP@50         {fmt(self.map50)}",
            f"  mAP@50-95      {fmt(self.map50_95)}",
            f"  Precision      {fmt(self.precision)}",
            f"  Recall         {fmt(self.recall)}",
            f"  F1             {fmt(self.f1)}",
            f"  Mean latency   {latency}",
        ]
        if self.per_class:
            lines += ["", "Per class:"]
            lines += [
                f"  {name:<24} AP@50 {fmt(scores.get('map50'))}"
                for name, scores in self.per_class.items()
            ]
        lines += [
            "",
            "These are measured values. Any metric shown as 'not measured' is",
            "reported as null in the registry rather than filled with a",
            "plausible number.",
            "=" * 62,
        ]
        return "\n".join(lines)


def evaluate_yolo(
    model_path: str,
    dataset_yaml: str,
    dataset_version: str,
    model_name: str = "yolo-pollution-detector",
    model_version: str = "yolov8m-best",
    latency_samples: int = 25,
) -> EvaluationReport:
    """Run ultralytics validation and measure inference latency.

    Args:
        model_path: Path to the ``.pt`` checkpoint.
        dataset_yaml: Path to a YOLO-format ``data.yaml``.
        dataset_version: Label recorded alongside the metrics.
        model_name: Registry name.
        model_version: Registry version.
        latency_samples: How many single-image passes to time.

    Returns:
        A populated :class:`EvaluationReport`.

    Raises:
        RuntimeError: If ultralytics is unavailable or the checkpoint is missing.
    """
    if not Path(model_path).exists():
        raise RuntimeError(f"Checkpoint not found: {model_path}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is required for evaluation: pip install ultralytics"
        ) from exc

    model = YOLO(model_path)
    results = model.val(data=dataset_yaml, verbose=False)

    box = getattr(results, "box", None)
    precision = float(box.mp) if box is not None else None
    recall = float(box.mr) if box is not None else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall) > 0
        else None
    )

    per_class = None
    names = getattr(results, "names", None) or getattr(model, "names", None)
    if box is not None and names is not None and hasattr(box, "maps"):
        per_class = {
            str(names[i]): {"map50": float(value)}
            for i, value in enumerate(box.maps)
            if i in names or str(i) in map(str, names)
        }

    # -- Latency, measured on real single-image passes --------------------
    mean_latency = None
    sample_dir = Path(dataset_yaml).parent
    images = [
        p
        for pattern in ("**/*.jpg", "**/*.png", "**/*.jpeg")
        for p in sample_dir.glob(pattern)
    ][:latency_samples]
    if images:
        timings: list[float] = []
        for image in images:
            started = time.perf_counter()
            model(str(image), verbose=False)
            timings.append((time.perf_counter() - started) * 1000)
        mean_latency = statistics.fmean(timings)

    return EvaluationReport(
        model_name=model_name,
        model_version=model_version,
        dataset_version=dataset_version,
        evaluated_at=datetime.now(UTC).isoformat(),
        n_images=len(images),
        map50=float(box.map50) if box is not None else None,
        map50_95=float(box.map) if box is not None else None,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_latency_ms=mean_latency,
        per_class=per_class,
    )


def register(report: EvaluationReport) -> None:
    """Write measured metrics into the model registry.

    Creates the registry row if it does not exist. ``metrics_source`` records
    that these numbers came from an evaluation run, which is what the
    ``/models`` endpoint uses to distinguish measured from unmeasured.
    """
    init_db()
    with SessionLocal() as db:
        from sqlalchemy import select

        model = db.scalar(
            select(ModelVersion).where(
                ModelVersion.name == report.model_name,
                ModelVersion.version == report.model_version,
            )
        )
        if model is None:
            model = ModelVersion(
                name=report.model_name,
                version=report.model_version,
                task="detection",
                framework="ultralytics-yolov8",
            )
            db.add(model)

        model.dataset_version = report.dataset_version
        model.map50 = report.map50
        model.map50_95 = report.map50_95
        model.precision = report.precision
        model.recall = report.recall
        model.f1 = report.f1
        model.mean_latency_ms = report.mean_latency_ms
        model.metrics_source = f"evaluate_detector.py @ {report.evaluated_at}"
        db.commit()

    print(f"Registered metrics for {report.model_name}:{report.model_version}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--dataset", required=True, help="YOLO data.yaml")
    parser.add_argument("--dataset-version", default="unversioned")
    parser.add_argument("--model-name", default="yolo-pollution-detector")
    parser.add_argument("--model-version", default="yolov8m-best")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument(
        "--register",
        action="store_true",
        help="Write metrics into the model registry.",
    )
    args = parser.parse_args()

    try:
        report = evaluate_yolo(
            model_path=args.model_path,
            dataset_yaml=args.dataset,
            dataset_version=args.dataset_version,
            model_name=args.model_name,
            model_version=args.model_version,
        )
    except RuntimeError as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report.to_dict(), indent=2) if args.json else report.render())

    if args.register:
        register(report)
    else:
        print("\n(Not registered. Pass --register to write these metrics.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
