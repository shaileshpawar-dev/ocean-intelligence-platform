"""Satellite data provider interface.

Keeping Earth Engine behind this interface means API routes never touch ``ee``
directly, the platform can run with no GEE credentials at all, and a second
source (Sentinel-2 optical, a local GeoTIFF archive, a commercial API) plugs
in without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.gee.regions import GridCell
from app.models.enums import EvidenceLevel


@dataclass(slots=True)
class ObservationDTO:
    """One satellite measurement over one grid cell.

    Every field here is a measurement or scene metadata. Nothing in this
    object is an interpretation -- that happens downstream in the detector.
    """

    cell_code: str
    cell_name: str
    collection: str
    platform: str
    acquired_at: datetime

    latitude: float
    longitude: float
    bbox: list[float]
    area_km2: float

    mean_db: float | None = None
    p10_db: float | None = None
    p90_db: float | None = None
    stddev_db: float | None = None
    min_db: float | None = None
    max_db: float | None = None

    scene_id: str | None = None
    instrument_mode: str | None = None
    polarisation: str | None = None
    orbit_pass: str | None = None
    scale_m: int | None = None
    scene_count: int | None = None

    evidence_level: EvidenceLevel = EvidenceLevel.OBSERVED
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise the measurement for API responses."""
        d = asdict(self)
        d["acquired_at"] = self.acquired_at.isoformat()
        d["evidence_level"] = str(self.evidence_level)
        return d

    def to_detector_input(self) -> dict:
        """Shape this observation for :class:`SARDarkFormationDetector`."""
        return {
            "region_code": self.cell_code,
            "mean_db": self.mean_db,
            "p10_db": self.p10_db,
            "p90_db": self.p90_db,
            "stddev_db": self.stddev_db,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "bbox": self.bbox,
            "area_km2": self.area_km2,
        }


class SatelliteDataProvider(ABC):
    """Interface for anything that can return satellite observations."""

    name: str = "base"

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can actually serve requests right now."""

    @abstractmethod
    def get_observations(
        self, cells: list[GridCell], lookback_days: int
    ) -> list[ObservationDTO]:
        """Return the most recent observation for each cell that has one.

        Cells with no usable scene in the window are omitted rather than
        filled in, so an absence of data reads as an absence of data.
        """

    @abstractmethod
    def get_thumbnail_url(self, bbox: list[float], dimensions: int = 512) -> str | None:
        """Return a rendered preview URL for a bounding box, if possible."""

    def describe(self) -> dict:
        """Provider metadata for the /health and /satellite endpoints."""
        return {"name": self.name, "available": self.is_available}
