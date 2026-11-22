r"""Replay the stored Sentinel-1 patches through the SAR screener and log them.

Inference latency read "Unavailable" and drift read "Insufficient data" because
``prediction_logs`` held two rows, both from the mock detector, both with no
detections. The platform had 306 real SAR patches on disk and a working
detector; nothing connected them.

This runs ``get_sar_v2_2_detector()`` over every patch and records each
inference through :func:`app.monitoring.prediction_log.log_prediction` -- the
same writer the live ``POST /api/v1/detect`` endpoint uses -- so latency and
drift see one consistent history.

Usage::

    python scripts/log_sar_inferences.py              # write
    python scripts/log_sar_inferences.py --dry-run    # measure, write nothing

Idempotent: each row's ``request_id`` is derived from the candidate id, and
existing rows are skipped unless ``--replace`` is passed.

About the timestamps
--------------------
The measurements here are real: the detector genuinely runs, and the latency
and confidence recorded are what it produced. What is **assigned** is the
``created_at`` that places each batch in a drift window, because all 306
inferences physically happen within a few seconds of each other and drift
compares two time windows.

The assignment is not arbitrary, and it is not tuned to produce a flattering
verdict. Drift compares the two independent held-out benchmarks against each
other:

* **baseline window** (8-36 days ago): Benchmark 1, the Phase 12 held-out set.
* **current window** (0-6 days ago): Benchmark 2, the Phase 13 locked final
  set, plus the acceptance fixtures.
* **outside both windows** (40+ days ago): the Phase 13 dev and validation
  sets. They are training-adjacent, so drift-comparing against them would be
  measuring the model against data it was tuned on. They are logged for
  latency and completeness, deliberately out of the comparison.

So the question the drift panel answers is a real one: *does the screener's
confidence distribution shift between two independent held-out benchmarks?*
Every row records ``timestamp_is_synthetic: true`` and its true wall-clock
execution time in ``input_stats``, and uses a ``BATCH`` endpoint label, so no
reader can mistake these for live API traffic.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.ml import PredictionLog  # noqa: E402
from app.models.sar_candidate import SARCandidate  # noqa: E402
from app.monitoring.prediction_log import log_prediction  # noqa: E402
from app.services.candidate_service import IMAGES_DIR  # noqa: E402
from app.vision.registry import get_sar_v2_2_detector  # noqa: E402

#: Marks these rows as a batch replay rather than live API traffic.
ENDPOINT = "BATCH /sar-candidates/replay"

#: Deterministic request ids, so a re-run updates rather than duplicates.
REQUEST_PREFIX = "sarreplay_"

#: Which drift window each split is placed in. See the module docstring.
BASELINE_SPLITS = {"Benchmark 1 (Phase 12 Held-Out Test Set)"}
CURRENT_SPLITS = {
    "Benchmark 2 (Phase 13 Locked Final Test Set)",
    "test_acceptance_phase13_3",
}

#: Day offsets, chosen to sit inside drift's default windows
#: (current = last 7 days, baseline = the 30 days before that).
CURRENT_SPAN = (0, 6)
BASELINE_SPAN = (8, 36)
OUTSIDE_SPAN = (40, 55)


def window_for(split: str) -> tuple[str, tuple[int, int]]:
    if split in BASELINE_SPLITS:
        return "baseline", BASELINE_SPAN
    if split in CURRENT_SPLITS:
        return "current", CURRENT_SPAN
    return "outside", OUTSIDE_SPAN


def spread(now: datetime, span: tuple[int, int], index: int, total: int) -> datetime:
    """Place the index-th row evenly across a span of days back from now."""
    lo, hi = span
    if total <= 1:
        offset = (lo + hi) / 2
    else:
        offset = hi - (hi - lo) * (index / (total - 1))
    return now - timedelta(days=offset)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="measure, write nothing")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete this script's previous rows and rewrite them",
    )
    args = parser.parse_args()

    detector = get_sar_v2_2_detector()
    if not detector.is_available:
        print("SAR v2.2 detector is not available (checkpoint missing?). Nothing done.")
        return 1
    print(f"detector: {detector.name} {detector.version}")

    with SessionLocal() as db:
        candidates = list(db.scalars(select(SARCandidate).order_by(SARCandidate.id)))
        print(f"candidates in database: {len(candidates)}")

        # Confirm every patch loads before writing anything.
        usable, missing = [], []
        for cand in candidates:
            path = IMAGES_DIR / cand.image_name
            (usable if path.exists() else missing).append((cand, path))
        print(f"patches present: {len(usable)}   missing: {len(missing)}")
        for cand, path in missing:
            print(f"  missing: {cand.candidate_id} -> {path.name}")

        if not usable:
            print("No patches to replay.")
            return 1

        existing = {
            r
            for r in db.scalars(
                select(PredictionLog.request_id).where(
                    PredictionLog.request_id.like(f"{REQUEST_PREFIX}%")
                )
            )
        }
        if existing and not args.replace:
            print(
                f"\n{len(existing)} replay rows already present; "
                "re-run with --replace to rewrite them."
            )
            return 0
        if existing and args.replace and not args.dry_run:
            removed = db.execute(
                delete(PredictionLog).where(
                    PredictionLog.request_id.like(f"{REQUEST_PREFIX}%")
                )
            ).rowcount
            db.commit()
            print(f"removed {removed} previous replay rows")

        # Group by window so each batch can be spread across its own span.
        by_window: dict[str, list] = {}
        for cand, path in usable:
            window, _ = window_for(cand.split)
            by_window.setdefault(window, []).append((cand, path))

        now = datetime.now(UTC)
        executed_at = now.isoformat()
        written = failed = 0
        latencies: list[float] = []
        per_window: Counter[str] = Counter()
        classes: Counter[str] = Counter()

        for window, rows in sorted(by_window.items()):
            _, span = window_for(rows[0][0].split)
            for index, (cand, path) in enumerate(rows):
                # The detector takes a path, a PIL image or an array -- not raw
                # bytes, which it silently rejects as an invalid payload and
                # returns zero detections for in well under a millisecond.
                payload = path
                started = time.perf_counter()
                error = None
                detections = []
                try:
                    detections = detector.predict(payload)
                except Exception as exc:  # noqa: BLE001
                    error = f"{exc.__class__.__name__}: {exc}"
                latency_ms = (time.perf_counter() - started) * 1000.0

                latencies.append(latency_ms)
                per_window[window] += 1
                for det in detections:
                    classes[str(det.signature)] += 1
                if error:
                    failed += 1

                if args.dry_run:
                    continue

                ok = log_prediction(
                    db,
                    request_id=f"{REQUEST_PREFIX}{cand.candidate_id}",
                    detector_name=detector.name,
                    version=detector.version,
                    latency_ms=latency_ms,
                    detections=detections,
                    error=error,
                    endpoint=ENDPOINT,
                    created_at=spread(now, span, index, len(rows)),
                    input_stats={
                        "candidate_id": cand.candidate_id,
                        "split": cand.split,
                        "subset": cand.subset,
                        "drift_window": window,
                        "image": cand.image_name,
                        # The measurements are real; the created_at is not.
                        "timestamp_is_synthetic": True,
                        "executed_at": executed_at,
                    },
                    commit=False,
                )
                written += int(ok)

        if not args.dry_run:
            db.commit()

    latencies.sort()
    mean = sum(latencies) / len(latencies)
    p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
    print(f"\ninferences run: {len(latencies)}   failures: {failed}")
    print(f"latency: mean {mean:.1f} ms   p95 {p95:.1f} ms   max {latencies[-1]:.1f} ms")
    print(f"predicted classes: {dict(classes.most_common())}")
    print("rows per drift window: " + ", ".join(f"{w}={n}" for w, n in sorted(per_window.items())))

    if args.dry_run:
        print("\n--dry-run: nothing written.")
    else:
        print(f"\nwritten: {written} prediction_logs rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
