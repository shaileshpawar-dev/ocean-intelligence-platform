r"""Fetch real Sentinel-2 optical evidence for SAR candidates.

For each candidate, finds the nearest Sentinel-2 L2A scene within ±5 days of
the SAR acquisition, retrieves six reflectance bands plus the scene
classification layer from Copernicus, and computes NDCI and NDTI on those
pixels.

A candidate with no cloud-free scene in the window gets **nothing**. There is
no synthetic fallback: a generated chip and a real one render identically,
which would make the panel worthless for the one thing it exists to do.

Usage:
    python scripts/rebuild_candidate_optical.py --limit 25
    python scripts/rebuild_candidate_optical.py --candidates cand_s1_0040
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.sar_candidate import SARCandidate  # noqa: E402
from app.services import candidate_service  # noqa: E402


def main(argv: list[str]) -> int:
    """Process optical evidence for the requested candidates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--chip-size", type=int, default=512)
    parser.add_argument("--candidates", nargs="*")
    args = parser.parse_args(argv[1:])

    with SessionLocal() as db:
        if args.candidates:
            ids = args.candidates
        else:
            ids = [
                row
                for (row,) in db.execute(
                    select(SARCandidate.candidate_id)
                    .order_by(func.random())
                    .limit(args.limit)
                ).all()
            ]

        real = absent = failed = 0
        for candidate_id in ids:
            try:
                evidence = candidate_service.process_candidate_optical_evidence(
                    db=db, candidate_id=candidate_id, chip_size=args.chip_size
                )
            except candidate_service.NoOpticalSceneError as exc:
                absent += 1
                print(f"  {candidate_id:22} none   {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  {candidate_id:22} FAILED {type(exc).__name__}: {exc}")
                continue
            real += 1
            # mean_ndci is nullable: a chip can be rendered from a scene whose
            # water pixels were all masked, and the index is then undefined.
            ndci = (
                f"{evidence.mean_ndci:+.4f}"
                if evidence.mean_ndci is not None
                else "n/a"
            )
            print(
                f"  {candidate_id:22} real   {evidence.scene_id[:38]} "
                f"cloud {evidence.scene_cloud_cover_pct:.1f}% "
                f"water {evidence.local_water_fraction:.0%} "
                f"NDCI {ndci}"
            )

    print(
        f"\n{real} with real Sentinel-2, {absent} with no cloud-free scene "
        f"within ±5 days, {failed} failed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
