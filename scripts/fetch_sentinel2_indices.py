r"""Fetch real Sentinel-2 water-quality indices for the monitored cells.

Walks the configured grid cells, asks Copernicus for NDCI, NDTI and FDI over
the last N days, and stores one row per (cell, acquisition date). Idempotent:
the unique constraint on (region, date) means a second run over the same
window inserts nothing.

Nothing is invented. A cell with no clear acquisition in the window is
reported as having none and stores no row -- it does not get a zero, and it
does not get the previous reading carried forward.

Usage:
    python scripts/fetch_sentinel2_indices.py
    python scripts/fetch_sentinel2_indices.py --days 30 --cloud 30
    python scripts/fetch_sentinel2_indices.py --cells gulf_of_kutch_w --thumbs
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.gee.regions import all_cells  # noqa: E402
from app.models import Region  # noqa: E402
from app.models.optical import OpticalIndexObservation  # noqa: E402
from app.vision.sentinel2_indices import (  # noqa: E402
    DEFAULT_MAX_CLOUD_PCT,
    DEFAULT_WINDOW_DAYS,
    get_sentinel2_client,
)


def main(argv: list[str]) -> int:
    """Fetch and store indices for every requested cell."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--cloud", type=int, default=DEFAULT_MAX_CLOUD_PCT)
    parser.add_argument(
        "--cells", nargs="*", help="Cell codes; default is every configured cell."
    )
    parser.add_argument(
        "--thumbs",
        action="store_true",
        help="Also fetch a true-colour thumbnail for each cell's newest reading.",
    )
    args = parser.parse_args(argv[1:])

    client = get_sentinel2_client()
    if not client.is_configured:
        print("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET are not set. Nothing fetched.")
        return 1

    cells = {c.code: c for c in all_cells()}
    wanted = args.cells or sorted(cells)
    missing = [c for c in wanted if c not in cells]
    if missing:
        print(f"Unknown cell(s): {', '.join(missing)}")
        return 2

    inserted = skipped = empty = failed = 0
    with SessionLocal() as db:
        regions = {r.code: r for r in db.scalars(select(Region)).all()}

        for code in wanted:
            cell = cells[code]
            region = regions.get(code)
            if region is None:
                print(f"  {code:34} no region row; run ingestion first")
                failed += 1
                continue

            outcome = client.fetch_cell(
                code,
                (cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat),
                window_days=args.days,
                max_cloud_pct=args.cloud,
            )
            if outcome.status != "ok":
                marker = {"no_acquisition": "none", "unconfigured": "unconfigured"}.get(
                    outcome.status, "FAILED"
                )
                print(f"  {code:34} {marker}: {outcome.detail}")
                empty += outcome.status == "no_acquisition"
                failed += outcome.status in {"error", "unconfigured"}
                continue

            new_rows = 0
            for reading in outcome.readings:
                exists = db.scalar(
                    select(OpticalIndexObservation.id).where(
                        OpticalIndexObservation.region_id == region.id,
                        OpticalIndexObservation.observed_on == reading.observed_on,
                    )
                )
                if exists:
                    skipped += 1
                    continue
                db.add(
                    OpticalIndexObservation(
                        region_id=region.id,
                        observed_on=reading.observed_on,
                        ndci_mean=reading.ndci_mean,
                        ndci_p50=reading.ndci_p50,
                        ndti_mean=reading.ndti_mean,
                        ndti_p50=reading.ndti_p50,
                        fdi_mean=reading.fdi_mean,
                        fdi_p90=reading.fdi_p90,
                        water_pixels=reading.water_pixels,
                        total_pixels=reading.total_pixels,
                        max_cloud_pct=reading.max_cloud_pct,
                        evidence_level=reading.evidence_level,
                        source=reading.source,
                        fetched_at=datetime.now(UTC),
                    )
                )
                new_rows += 1
            db.commit()
            inserted += new_rows

            newest = outcome.readings[0]
            thumb = ""
            if args.thumbs:
                path = client.fetch_thumbnail(
                    code,
                    (cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat),
                    newest.observed_on,
                )
                thumb = f" thumb={'yes' if path else 'no'}"
            print(
                f"  {code:34} {len(outcome.readings):2d} acquisitions, "
                f"{new_rows:2d} new, newest {newest.observed_on} "
                f"ndci={newest.ndci_mean:+.3f} fdi={newest.fdi_mean:+.4f} "
                f"water={newest.water_fraction:.0%}{thumb}"
            )

    print(
        f"\n{inserted} inserted, {skipped} already stored, "
        f"{empty} cell(s) with no clear acquisition, {failed} failed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
