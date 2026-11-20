"""Monitoring region definitions and grid subdivision.

These are the Indian EEZ and the waters immediately around it. They replaced
an inherited global set -- Gulf of Mexico, North Sea, Yellow Sea and the like
-- which made the marine module read as a second, unrelated project beside
the India water work, and which no part of the platform was actually built
around.

The environmental receptors were already Indian (Gulf of Mannar, the
Sundarbans, the Gulf of Kachchh Marine National Park, Malvan, the Chennai
desalination intake), so impact screening could never fire: a detection in
the Gulf of Mexico cannot threaten a reef off Tamil Nadu. Matching the
regions to the receptors is what makes that screening mean anything.

Each region is a real area of operational interest rather than a tidy
rectangle: the Gulf of Kutch carries the Vadinar and Kandla oil terminals,
Mumbai Offshore covers the Mumbai High field, Krishna--Godavari covers the
offshore gas basin, and Paradip, Kochi and Chennai sit against their coastal
cells.

Cells are stable, named entities persisted in the ``regions`` table rather
than strings rebuilt on every fetch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.risk.geo import EARTH_RADIUS_KM


@dataclass(frozen=True, slots=True)
class RegionDefinition:
    """A monitored sea area and how finely to subdivide it."""

    name: str
    #: [min_lon, min_lat, max_lon, max_lat] in WGS84.
    bbox: tuple[float, float, float, float]
    #: (columns, rows) grid subdivision.
    grid: tuple[int, int]


#: Why each region is monitored, carried into the UI so a reader is never
#: left wondering why a rectangle of sea is on the list.
REGION_RATIONALE: dict[str, str] = {
    "Gulf of Kutch": "Vadinar and Kandla crude terminals; Marine National Park",
    "Gulf of Khambhat": "Dahej and Hazira industrial estuary",
    "Mumbai Offshore": "Mumbai High oil field and the JNPT approach",
    "Konkan & Goa Coast": "Mormugao ore and fuel traffic; Malvan Marine Sanctuary",
    "Malabar Coast": "Kochi refinery and port; monsoon-exposed shelf",
    "Lakshadweep Sea": "Atoll reefs astride the Gulf-to-Asia tanker route",
    "Gulf of Mannar": "Marine Biosphere Reserve; coral and seagrass",
    "Palk Bay": "Shallow, enclosed, dugong and seagrass habitat",
    "Coromandel Coast": "Chennai and Ennore ports; Nemmeli desalination intake",
    "Krishna-Godavari Offshore": "Offshore gas basin and its supply traffic",
    "Odisha Coast": "Paradip port and refinery; Olive Ridley nesting shelf",
    "Sundarbans & Bengal": "UNESCO mangrove delta; Haldia approach",
    "Andaman Sea": "Island reefs; Malacca approaches",
    "Arabian Sea": "Open-water transit west of the shelf",
    "Bay of Bengal": "Open-water transit east of the shelf",
}

REGIONS: tuple[RegionDefinition, ...] = (
    # -- West coast, north to south -------------------------------------
    RegionDefinition("Gulf of Kutch", (68.3, 22.0, 70.4, 23.3), (2, 1)),
    RegionDefinition("Gulf of Khambhat", (71.6, 20.6, 72.9, 22.3), (1, 1)),
    RegionDefinition("Mumbai Offshore", (71.3, 18.6, 72.8, 20.3), (2, 1)),
    RegionDefinition("Konkan & Goa Coast", (72.4, 14.8, 73.8, 17.6), (1, 2)),
    RegionDefinition("Malabar Coast", (74.2, 8.2, 76.3, 12.4), (1, 2)),
    RegionDefinition("Lakshadweep Sea", (70.8, 8.0, 74.0, 13.0), (2, 2)),
    # -- Southern tip ----------------------------------------------------
    RegionDefinition("Gulf of Mannar", (78.1, 8.3, 79.4, 9.4), (1, 1)),
    RegionDefinition("Palk Bay", (79.0, 9.2, 80.2, 10.3), (1, 1)),
    # -- East coast, south to north --------------------------------------
    RegionDefinition("Coromandel Coast", (80.0, 10.6, 81.3, 13.9), (1, 2)),
    RegionDefinition("Krishna-Godavari Offshore", (81.2, 14.4, 84.0, 17.3), (2, 2)),
    RegionDefinition("Odisha Coast", (86.2, 19.4, 87.8, 21.2), (2, 1)),
    RegionDefinition("Sundarbans & Bengal", (87.8, 20.4, 89.3, 21.7), (1, 1)),
    # -- Islands and open water ------------------------------------------
    RegionDefinition("Andaman Sea", (91.6, 9.2, 94.4, 13.9), (2, 2)),
    RegionDefinition("Arabian Sea", (64.0, 12.0, 71.5, 21.5), (3, 2)),
    RegionDefinition("Bay of Bengal", (82.0, 10.5, 89.5, 18.5), (3, 2)),
)


@dataclass(frozen=True, slots=True)
class GridCell:
    """One subdivision of a region, the unit of observation."""

    code: str
    name: str
    parent_name: str
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def centroid(self) -> tuple[float, float]:
        """(latitude, longitude) of the cell centre."""
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )

    @property
    def bbox(self) -> list[float]:
        """[min_lon, min_lat, max_lon, max_lat]."""
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]

    @property
    def area_km2(self) -> float:
        """Approximate cell area on a spherical Earth.

        Uses the exact spherical-rectangle formula (integrating cos(lat)),
        so it stays correct at high latitude where a naive
        ``dlat * dlon * 111^2`` over-estimates badly.
        """
        lat1, lat2 = math.radians(self.min_lat), math.radians(self.max_lat)
        dlon = math.radians(self.max_lon - self.min_lon)
        return abs(EARTH_RADIUS_KM**2 * dlon * (math.sin(lat2) - math.sin(lat1)))


def _slug(text: str) -> str:
    """Lowercase, underscore-separated identifier.

    Runs of separators collapse to one, so "Konkan & Goa Coast" becomes
    ``konkan_goa_coast`` rather than ``konkan___goa_coast``.
    """
    raw = "".join(c if c.isalnum() else "_" for c in text.lower())
    return "_".join(part for part in raw.split("_") if part)


def build_grid(region: RegionDefinition) -> list[GridCell]:
    """Subdivide a region into its grid cells.

    Cells are named by compass position for 2x2 and smaller grids and by
    index otherwise, matching the original naming so existing screenshots and
    notes stay meaningful.
    """
    min_lon, min_lat, max_lon, max_lat = region.bbox
    cols, rows = region.grid
    dlon = (max_lon - min_lon) / cols
    dlat = (max_lat - min_lat) / rows

    compass = ["SW", "SE", "NW", "NE"]
    cells: list[GridCell] = []
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            # The compass label has to match the grid shape or it misnames the
            # cell: a region split only north-to-south has no western half, so
            # "SW"/"SE" for its two halves was simply wrong.
            if cols * rows == 1:
                label = ""          # the cell is the whole region
            elif cols == 1 and rows == 2:
                label = ("S", "N")[index]
            elif cols == 2 and rows == 1:
                label = ("W", "E")[index]
            elif cols == 2 and rows == 2:
                label = compass[index]
            else:
                label = f"Z{index + 1}"
            name = f"{region.name} {label}".strip()
            cells.append(
                GridCell(
                    code=_slug(name),
                    name=name,
                    parent_name=region.name,
                    min_lon=min_lon + col * dlon,
                    min_lat=min_lat + row * dlat,
                    max_lon=min_lon + (col + 1) * dlon,
                    max_lat=min_lat + (row + 1) * dlat,
                )
            )
    return cells


def all_cells() -> list[GridCell]:
    """Every grid cell across every monitored region."""
    return [cell for region in REGIONS for cell in build_grid(region)]
