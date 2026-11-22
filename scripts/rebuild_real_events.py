r"""Rebuild pollution events and daily history from the stored real readings.

Run after a Sentinel-2 fetch. Two steps, both idempotent:

1. Raise pollution events for index readings that clear their thresholds
   (see ``app.services.optical_events`` for where the thresholds come from
   and what they do and do not claim).
2. Recompute the daily ``zone_history`` buckets the analytics and forecast
   layers read.

Nothing here invents data: it only derives from readings already measured and
stored. A region with no qualifying reading gets no event and no bucket.

Usage:
    python scripts/rebuild_real_events.py
    python scripts/rebuild_real_events.py --rebuild-events   # drop and redo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import PollutionEvent, RiskAssessment  # noqa: E402
from app.models.enums import DetectionMethod  # noqa: E402
from app.services.analytics_service import rebuild_history  # noqa: E402
from app.services.optical_events import build_optical_events  # noqa: E402


def main(argv: list[str]) -> int:
    """Raise events from stored readings, then rebuild daily history."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild-events",
        action="store_true",
        help=(
            "Delete existing optical-index events first. Needed after a "
            "threshold change, since the builder is otherwise idempotent and "
            "would leave the old ones in place."
        ),
    )
    args = parser.parse_args(argv[1:])

    with SessionLocal() as db:
        if args.rebuild_events:
            stale = [
                row_id
                for (row_id,) in db.execute(
                    select(PollutionEvent.id).where(
                        PollutionEvent.detection_method
                        == str(DetectionMethod.OPTICAL_INDEX)
                    )
                ).all()
            ]
            if stale:
                db.query(RiskAssessment).filter(
                    RiskAssessment.event_id.in_(stale)
                ).delete(synchronize_session=False)
                db.query(PollutionEvent).filter(
                    PollutionEvent.id.in_(stale)
                ).delete(synchronize_session=False)
                db.commit()
            print(f"Removed {len(stale)} existing optical-index event(s).")

        summary = build_optical_events(db)
        print(json.dumps(summary, indent=1))

        buckets = rebuild_history(db)
        regions_with_history = db.scalar(
            select(func.count(func.distinct(PollutionEvent.region_id)))
        )
        print(
            f"\n{buckets} daily history bucket(s) rebuilt across "
            f"{regions_with_history} region(s) with events."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
