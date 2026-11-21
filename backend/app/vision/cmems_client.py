"""Copernicus Marine: surface currents, and chlorophyll as a cross-check.

Two products, used for two different jobs.

**Surface currents** (``cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m``, the
global ocean physics analysis and forecast at 1/12 degree). The drift
simulator has always taken a current speed and bearing as arguments, with
defaults of 0.22 m/s due east baked into the engine. Those defaults are a
placeholder, and a drift track computed from a placeholder current is a
drawing. This replaces them with the modelled current where the spill
actually is -- and when it cannot, the simulation says so rather than
silently reverting to 0.22.

**Chlorophyll-a** (``cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km``,
L4 gap-free multi-sensor ocean colour). Not used for detection: it sits
beside NDCI as an independent estimate of the same quantity. NDCI is a
two-band ratio this platform computes from raw reflectance; the CMEMS product
is a validated, atmospherically-corrected, multi-sensor retrieval. Where they
agree, the NDCI reading is more trustworthy. Where they disagree, that is
worth seeing rather than hiding, so both are shown and neither is corrected
to match the other.

**Evidence level.** Currents are ``INFERRED`` -- an ocean model's analysis,
not a measurement. Chlorophyll is ``OBSERVED``: it is a satellite retrieval,
processed but derived from radiance the sensor actually recorded.

Every fetch is cached to disk. The toolbox reads from object storage lazily,
which is quick for a small box but not quick enough to sit in a request.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Copernicus Marine asks that products be credited by name.
ATTRIBUTION = "Generated using E.U. Copernicus Marine Service Information"
SERVICE = "Copernicus Marine Service"

CURRENTS_DATASET = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"
CURRENTS_PRODUCT = "Global Ocean Physics Analysis and Forecast (1/12 deg, daily mean)"
#: A model analysis, not a measurement.
CURRENTS_EVIDENCE = "INFERRED"

CHLOROPHYLL_DATASET = "cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km_P1D"
CHLOROPHYLL_PRODUCT = (
    "Global Ocean Colour, L4 gap-free multi-sensor chlorophyll-a (4 km, daily)"
)
#: A satellite retrieval: processed, but derived from recorded radiance.
CHLOROPHYLL_EVIDENCE = "OBSERVED"

CACHE_DIR = Path(
    settings.water_cache_dir
    if Path(settings.water_cache_dir).is_absolute()
    else REPO_ROOT / settings.water_cache_dir
) / "cmems"


@dataclass(slots=True)
class CurrentReading:
    """Modelled surface current over one box, on one day."""

    cell_code: str
    valid_on: str
    u_ms: float
    v_ms: float

    @property
    def speed_ms(self) -> float:
        """Current speed."""
        return math.hypot(self.u_ms, self.v_ms)

    @property
    def direction_deg(self) -> float:
        """Bearing the current flows *toward*, degrees clockwise from north.

        The oceanographic convention, and the one the drift engine expects.
        The meteorological convention (the direction wind comes *from*) is
        the opposite, which is a 180-degree error if the two are confused.
        """
        return (math.degrees(math.atan2(self.u_ms, self.v_ms)) + 360.0) % 360.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise with provenance."""
        return {
            "cell_code": self.cell_code,
            "valid_on": self.valid_on,
            "u_ms": round(self.u_ms, 4),
            "v_ms": round(self.v_ms, 4),
            "speed_ms": round(self.speed_ms, 4),
            "direction_deg": round(self.direction_deg, 1),
            "evidence_level": CURRENTS_EVIDENCE,
            "dataset": CURRENTS_DATASET,
            "product": CURRENTS_PRODUCT,
            "service": SERVICE,
            "attribution": ATTRIBUTION,
        }


@dataclass(slots=True)
class ChlorophyllReading:
    """Satellite chlorophyll-a over one box, on one day."""

    cell_code: str
    valid_on: str
    chl_mg_m3: float
    valid_pixels: int

    def to_dict(self) -> dict[str, Any]:
        """Serialise with provenance."""
        return {
            "cell_code": self.cell_code,
            "valid_on": self.valid_on,
            "chl_mg_m3": round(self.chl_mg_m3, 4),
            "valid_pixels": self.valid_pixels,
            "evidence_level": CHLOROPHYLL_EVIDENCE,
            "dataset": CHLOROPHYLL_DATASET,
            "product": CHLOROPHYLL_PRODUCT,
            "service": SERVICE,
            "attribution": ATTRIBUTION,
        }


class CMEMSClient:
    """Copernicus Marine reads, cached to disk."""

    def __init__(self) -> None:
        """Ensure the cache directory exists."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def is_configured(self) -> bool:
        """True when a Copernicus Marine account is configured."""
        return bool(settings.cmems_username and settings.cmems_password)

    def _open(self, dataset_id: str, variables: list[str], bbox, depth: bool):
        """Open a lazy subset of one dataset over ``bbox``."""
        import copernicusmarine as cm

        min_lon, min_lat, max_lon, max_lat = bbox
        kwargs: dict[str, Any] = {
            "dataset_id": dataset_id,
            "variables": variables,
            "minimum_longitude": min_lon,
            "maximum_longitude": max_lon,
            "minimum_latitude": min_lat,
            "maximum_latitude": max_lat,
            "username": settings.cmems_username,
            "password": settings.cmems_password,
        }
        if depth:
            # The shallowest level the model carries, not literally zero:
            # the grid's first depth is ~0.49 m and asking for 0 warns.
            kwargs["minimum_depth"] = 0.0
            kwargs["maximum_depth"] = 1.0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return cm.open_dataset(**kwargs)

    def fetch_current(
        self,
        cell_code: str,
        bbox: tuple[float, float, float, float],
        *,
        on: date | None = None,
        use_cache: bool = True,
    ) -> CurrentReading | None:
        """Mean surface current over a box, for the nearest available day.

        Returns ``None`` when Copernicus cannot be reached or the box holds no
        water. The caller must treat that as "unknown", never as "still".
        """
        target = on or datetime.now(UTC).date()
        cache_file = CACHE_DIR / f"current_{cell_code}_{target.isoformat()}.json"
        if use_cache and cache_file.exists():
            try:
                return CurrentReading(**json.loads(cache_file.read_text("utf-8")))
            except (json.JSONDecodeError, TypeError):
                pass

        if not self.is_configured:
            return None
        try:
            import numpy as np

            dataset = self._open(CURRENTS_DATASET, ["uo", "vo"], bbox, depth=True)
            # The product runs ten days ahead, so the last time step is a
            # forecast. Pick the step nearest the requested day instead.
            stamp = np.datetime64(target.isoformat())
            index = int(np.abs(dataset.time.values - stamp).argmin())
            slab = dataset.isel(time=index)
            u = float(np.nanmean(slab.uo.values))
            v = float(np.nanmean(slab.vo.values))
            valid_on = str(dataset.time.values[index])[:10]
        except Exception as exc:  # noqa: BLE001
            logger.warning("cmems_current_failed", extra={"error": type(exc).__name__})
            return None

        if math.isnan(u) or math.isnan(v):
            # Every cell in the box is land, so there is no current to report.
            return None

        reading = CurrentReading(
            cell_code=cell_code, valid_on=valid_on, u_ms=u, v_ms=v
        )
        cache_file.write_text(
            json.dumps(
                {
                    "cell_code": cell_code,
                    "valid_on": valid_on,
                    "u_ms": u,
                    "v_ms": v,
                }
            ),
            encoding="utf-8",
        )
        return reading

    def fetch_chlorophyll(
        self,
        cell_code: str,
        bbox: tuple[float, float, float, float],
        *,
        on: date | None = None,
        lookback_days: int = 7,
        use_cache: bool = True,
    ) -> ChlorophyllReading | None:
        """Mean chlorophyll-a over a box, from the most recent day with data.

        Ocean colour needs daylight and a clear sky, so the newest file is
        often mostly gaps. The last ``lookback_days`` are searched newest
        first and the first day with valid pixels is returned, carrying its
        own date -- not the date it was asked for.
        """
        target = on or datetime.now(UTC).date()
        cache_file = CACHE_DIR / f"chl_{cell_code}_{target.isoformat()}.json"
        if use_cache and cache_file.exists():
            try:
                return ChlorophyllReading(**json.loads(cache_file.read_text("utf-8")))
            except (json.JSONDecodeError, TypeError):
                pass

        if not self.is_configured:
            return None
        try:
            import numpy as np

            dataset = self._open(CHLOROPHYLL_DATASET, ["CHL"], bbox, depth=False)
            times = dataset.time.values
            window_start = np.datetime64((target - timedelta(days=lookback_days)).isoformat())
            window_end = np.datetime64(target.isoformat()) + np.timedelta64(1, "D")
            candidates = [
                i
                for i, t in enumerate(times)
                if window_start <= t <= window_end
            ]
            for index in reversed(candidates):
                values = dataset.isel(time=index).CHL.values
                valid = int(np.count_nonzero(~np.isnan(values)))
                if valid == 0:
                    continue
                mean = float(np.nanmean(values))
                reading = ChlorophyllReading(
                    cell_code=cell_code,
                    valid_on=str(times[index])[:10],
                    chl_mg_m3=mean,
                    valid_pixels=valid,
                )
                cache_file.write_text(
                    json.dumps(
                        {
                            "cell_code": cell_code,
                            "valid_on": reading.valid_on,
                            "chl_mg_m3": mean,
                            "valid_pixels": valid,
                        }
                    ),
                    encoding="utf-8",
                )
                return reading
        except Exception as exc:  # noqa: BLE001
            logger.warning("cmems_chl_failed", extra={"error": type(exc).__name__})
            return None
        return None


_client: CMEMSClient | None = None


def get_cmems_client() -> CMEMSClient:
    """Process-wide client."""
    global _client
    if _client is None:
        _client = CMEMSClient()
    return _client
