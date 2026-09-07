"""Monitoring region definitions and grid subdivision.

The twelve regions and their grid shapes are carried over unchanged from the
original notebook -- the region selection was sound (busy shipping lanes,
known spill hotspots, semi-enclosed seas) and there is no reason to rebuild
it. What changed is that cells are now stable, named entities persisted in
the ``regions`` table rather than strings rebuilt on every fetch.
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


REGIONS: tuple[RegionDefinition, ...] = (
    RegionDefinition("Arabian Sea", (58.0, 10.0, 74.0, 26.0), (2, 2)),
    RegionDefinition("Bay of Bengal", (80.0, 8.0, 95.0, 20.0), (2, 2)),
    RegionDefinition("Persian Gulf", (48.0, 22.0, 58.0, 28.0), (2, 1)),
    RegionDefinition("Mediterranean", (5.0, 30.0, 36.0, 46.0), (3, 2)),
    RegionDefinition("South China Sea", (108.0, 5.0, 120.0, 22.0), (2, 2)),
    RegionDefinition("Gulf of Guinea", (-2.0, -5.0, 15.0, 5.0), (2, 1)),
    RegionDefinition("Red Sea", (32.0, 12.0, 44.0, 28.0), (1, 2)),
    RegionDefinition("Gulf of Mexico", (-97.0, 18.0, -80.0, 30.0), (2, 2)),
    RegionDefinition("North Sea", (-2.0, 51.0, 10.0, 58.0), (2, 1)),
    RegionDefinition("Strait of Malacca", (99.0, 1.0, 106.0, 7.0), (2, 1)),
    RegionDefinition("Yellow Sea", (119.0, 29.0, 127.0, 38.0), (2, 2)),
    RegionDefinition("Java Sea", (106.0, -8.0, 116.0, -3.0), (2, 1)),
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
    """Lowercase, underscore-separated identifier."""
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


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
            if cols * rows <= 4:
                label = compass[index] if index < len(compass) else f"Z{index + 1}"
            else:
                label = f"Z{index + 1}"
            name = f"{region.name} {label}"
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
