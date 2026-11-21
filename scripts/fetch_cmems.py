r"""Cache Copernicus Marine currents and chlorophyll for every region.

Surface currents feed the drift simulator, replacing a hardcoded placeholder.
Chlorophyll sits beside the platform's own NDCI as an independent estimate of
the same quantity; neither is adjusted to agree with the other.

Both are written to the disk cache the application reads, so a page load and
a drift run never wait on Copernicus.

Usage:
    python scripts/fetch_cmems.py
    python scripts/fetch_cmems.py --cells gulf_of_kutch_w gulf_of_mannar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.gee.regions import all_cells  # noqa: E402
from app.vision.cmems_client import get_cmems_client  # noqa: E402


def main(argv: list[str]) -> int:
    """Fetch currents and chlorophyll for the requested cells."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", nargs="*")
    args = parser.parse_args(argv[1:])

    client = get_cmems_client()
    if not client.is_configured:
        print("CMEMS_USERNAME / CMEMS_PASSWORD are not set. Nothing fetched.")
        return 1

    cells = {c.code: c for c in all_cells()}
    wanted = args.cells or sorted(cells)

    currents = chlorophyll = 0
    for code in wanted:
        cell = cells[code]
        bbox = (cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat)

        current = client.fetch_current(code, bbox)
        chl = client.fetch_chlorophyll(code, bbox)
        currents += current is not None
        chlorophyll += chl is not None

        current_text = (
            f"{current.speed_ms:.3f} m/s toward {current.direction_deg:3.0f}deg "
            f"({current.valid_on})"
            if current
            else "unavailable"
        )
        chl_text = (
            f"{chl.chl_mg_m3:6.3f} mg/m3 ({chl.valid_on}, {chl.valid_pixels} px)"
            if chl
            else "unavailable"
        )
        print(f"  {code:32} current {current_text:38} chl {chl_text}")

    print(
        f"\n{currents}/{len(wanted)} currents, "
        f"{chlorophyll}/{len(wanted)} chlorophyll cached."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
