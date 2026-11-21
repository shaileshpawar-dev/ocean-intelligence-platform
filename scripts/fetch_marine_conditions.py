r"""Refresh current wind, wave and sea-surface conditions from Open-Meteo.

Two requests for all forty regions, written to the cache the API serves from.
Run it before a demo; the platform then shows the conditions as of that run,
with the time of the run attached, and makes no live call.

Usage:
    python scripts/fetch_marine_conditions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.gee.regions import all_cells  # noqa: E402
from app.vision.marine_conditions import (  # noqa: E402
    CACHE_FILE,
    LOW_WIND_MS,
    get_marine_conditions_client,
)


def main() -> int:
    """Fetch every region's conditions and write the cache."""
    client = get_marine_conditions_client()
    points = [
        (cell.code, cell.centroid[0], cell.centroid[1])
        for cell in sorted(all_cells(), key=lambda c: c.code)
    ]

    readings, error = client.fetch(points)
    client.save(readings, error)

    with_wind = [r for r in readings if r.wind_speed_ms is not None]
    with_waves = [r for r in readings if r.wave_height_m is not None]
    ambiguous = [r for r in readings if r.sar_ambiguous]

    print(f"{len(readings)} region(s) requested")
    print(f"  wind:  {len(with_wind)} answered")
    print(f"  waves: {len(with_waves)} answered")
    if error:
        print(f"  partial failure, recorded rather than filled in: {error}")
    print(
        f"  {len(ambiguous)} region(s) below {LOW_WIND_MS} m/s -- SAR dark "
        "formations there are ambiguous right now"
    )
    print(f"\nCached to {CACHE_FILE}")
    return 0 if with_wind else 1


if __name__ == "__main__":
    raise SystemExit(main())
