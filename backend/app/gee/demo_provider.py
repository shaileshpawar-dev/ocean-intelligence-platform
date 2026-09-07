"""Deterministic synthetic satellite provider for demo mode and tests.

Generates backscatter statistics with a plausible open-ocean distribution so
the whole downstream pipeline -- detector, risk engine, analytics, forecast --
can be exercised without Earth Engine credentials.

Everything it returns is tagged ``EvidenceLevel.SIMULATED`` and the API
propagates that tag to the client. The dashboard renders simulated rows with
a persistent banner. This is the mechanism that makes demo mode safe to show
in an interview: it is impossible to display a simulated value as an
observation.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

from app.gee.base import ObservationDTO, SatelliteDataProvider
from app.gee.regions import GridCell
from app.models.enums import EvidenceLevel

#: Typical open-ocean VV backscatter at moderate wind, in dB.
BASE_MEAN_DB = -14.0


def _unit_hash(*parts: str) -> float:
    """Stable pseudo-random float in [0, 1) from string inputs."""
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


class DemoSatelliteProvider(SatelliteDataProvider):
    """Reproducible synthetic Sentinel-1-shaped observations."""

    name = "demo-synthetic"

    def __init__(self, seed: str = "oip-demo-v1") -> None:
        """Seed the generator so output is reproducible across runs."""
        self.seed = seed

    @property
    def is_available(self) -> bool:
        """Always available; that is the point of demo mode."""
        return True

    def get_observations(
        self, cells: list[GridCell], lookback_days: int = 10
    ) -> list[ObservationDTO]:
        """Generate one synthetic observation per cell.

        A deterministic minority of cells are given a genuine dark-formation
        signature -- low p10 with high contrast -- so the detector has
        something real to find. The majority look like ordinary sea, so the
        detector also returns honest negatives.
        """
        # Anchor to the start of the current UTC day rather than "now", so a
        # given cell reports the same acquisition time on every call within a
        # day. Real scenes have fixed acquisition timestamps, and the
        # ingestion layer de-duplicates on them -- a drifting timestamp would
        # make every re-ingest look like a new observation.
        now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        observations: list[ObservationDTO] = []

        for index, cell in enumerate(cells):
            roll = _unit_hash(self.seed, cell.code)
            lat, lon = cell.centroid

            # Latitude modulates the sea state: higher latitudes are windier
            # and therefore brighter in VV.
            lat_effect = 2.0 * math.cos(math.radians(lat))
            mean_db = BASE_MEAN_DB + lat_effect + (roll - 0.5) * 4.0

            if roll < 0.18:
                # Dark formation: a distinctly dark tail against a normal sea.
                p10_db = mean_db - 12.0 - roll * 10.0
                p90_db = mean_db + 4.0
                stddev = 6.5
            elif roll < 0.28:
                # Uniformly dark: the low-wind look-alike the detector should
                # refuse to call an oil signature.
                mean_db = -24.0 - roll * 3.0
                p10_db = mean_db - 1.2
                p90_db = mean_db + 1.4
                stddev = 1.1
            else:
                # Ordinary sea surface.
                p10_db = mean_db - 5.0 - roll * 2.0
                p90_db = mean_db + 4.5
                stddev = 3.2

            acquired = now - timedelta(
                hours=int(roll * lookback_days * 24), minutes=index
            )

            observations.append(
                ObservationDTO(
                    cell_code=cell.code,
                    cell_name=cell.name,
                    collection="DEMO/S1_GRD_SYNTHETIC",
                    platform="Sentinel-1 (simulated)",
                    acquired_at=acquired,
                    latitude=lat,
                    longitude=lon,
                    bbox=cell.bbox,
                    area_km2=round(cell.area_km2, 2),
                    mean_db=round(mean_db, 2),
                    p10_db=round(p10_db, 2),
                    p90_db=round(p90_db, 2),
                    stddev_db=round(stddev, 2),
                    min_db=round(p10_db - 4.0, 2),
                    max_db=round(p90_db + 3.0, 2),
                    scene_id=f"DEMO_{cell.code}_{int(acquired.timestamp())}",
                    instrument_mode="IW",
                    polarisation="VV",
                    orbit_pass="DESCENDING" if index % 2 else "ASCENDING",
                    scale_m=500,
                    scene_count=1,
                    evidence_level=EvidenceLevel.SIMULATED,
                    extra={
                        "simulated": True,
                        "notice": (
                            "SIMULATED OBSERVATION. Generated by the demo "
                            "provider. Does not describe any real satellite "
                            "acquisition."
                        ),
                    },
                )
            )
        return observations

    def get_thumbnail_url(self, bbox: list[float], dimensions: int = 512) -> str | None:
        """No imagery in demo mode; the API surfaces this as an explicit null."""
        return None
