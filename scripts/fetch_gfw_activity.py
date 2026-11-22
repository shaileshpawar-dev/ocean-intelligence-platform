r"""Cache Global Fishing Watch vessel activity for every monitored region.

Aggregate only: hours and vessel counts per region, grouped by flag state.
No vessel identity is fetched or stored -- see app/vision/gfw_client.py for
why that is a deliberate limit rather than an omission.

GFW's effort product lags real time by roughly a week while AIS is processed,
so the window ends ``--lag-days`` before today. Asking for the last 45 days
up to this morning returns zeros everywhere, which looks like empty ocean and
is really just an unprocessed week.

Usage:
    python scripts/fetch_gfw_activity.py
    python scripts/fetch_gfw_activity.py --days 45 --lag-days 7
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.gee.regions import all_cells  # noqa: E402
from app.vision.gfw_client import DEFAULT_WINDOW_DAYS, get_gfw_client  # noqa: E402


def main(argv: list[str]) -> int:
    """Fetch and cache aggregate activity for every region."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--lag-days", type=int, default=7)
    parser.add_argument("--cells", nargs="*")
    args = parser.parse_args(argv[1:])

    client = get_gfw_client()
    if not client.is_configured:
        print("GFW_API_TOKEN is not set. Nothing fetched.")
        return 1

    end = datetime.now(UTC).date() - timedelta(days=args.lag_days)
    cells = {c.code: c for c in all_cells()}
    wanted = args.cells or sorted(cells)

    answered = active = 0
    total_hours = 0.0
    for code in wanted:
        cell = cells[code]
        activity = client.fetch_region(
            code,
            (cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat),
            window_days=args.days,
            today=end,
        )
        if activity is None:
            print(f"  {code:32} unavailable")
            continue
        answered += 1
        total_hours += activity.total_hours
        if activity.total_hours > 0:
            active += 1
            flags = ", ".join(f"{f} {h:.0f}h" for f, h in activity.top_flags[:3])
            print(
                f"  {code:32} {activity.total_hours:9.1f} h  "
                f"{activity.vessel_count:4d} vessels  [{flags}]"
            )
        else:
            # Zero is a finding, not a failure: GFW answered, and reported
            # no apparent fishing effort in this water.
            print(f"  {code:32}       none observed")

    print(
        f"\n{answered}/{len(wanted)} regions answered, {active} with activity, "
        f"{total_hours:,.0f} vessel-hours total "
        f"(window {args.days} days ending {end})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
