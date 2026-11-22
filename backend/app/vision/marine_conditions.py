"""Current wind, wave and sea-surface conditions from Open-Meteo.

Measured and modelled conditions for each monitored region, refreshed on
demand and cached so a page load never waits on a weather service. Two free
endpoints, no key, no registration:

* ``api.open-meteo.com/v1/forecast`` -- 10 m wind speed, direction and gusts.
* ``marine-api.open-meteo.com/v1/marine`` -- significant wave height, wave
  period, and sea-surface temperature.

Both are queried for every region in a single request each: Open-Meteo accepts
comma-separated coordinates and returns one object per location in order, so
40 regions cost two calls rather than eighty.

**What this is, in evidence terms.** These are not satellite observations.
Open-Meteo serves numerical weather prediction output -- an analysis of
conditions, constrained by measurements but produced by a model. So the
evidence level is ``INFERRED``, not ``OBSERVED``, and the provider is named
wherever a value is shown. Calling a model's wave height an observation
because it happens to be accurate would make the distinction meaningless
everywhere else it matters.

Wind matters here beyond display. Dark formations in SAR are ambiguous below
roughly 3 m/s, because low wind flattens the sea surface and looks like oil.
The wind screener already collocates each candidate against ERA5 reanalysis
for its own acquisition time; this module answers the different question of
what the wind is doing in a region *now*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

#: Shown wherever these values appear. Open-Meteo asks only that it be named.
ATTRIBUTION = "Weather and marine data by Open-Meteo.com"
PROVIDER = "Open-Meteo"

#: A model analysis, not a measurement. See the module docstring.
EVIDENCE_LEVEL = "INFERRED"

#: Below this, SAR dark formations are ambiguous: a flat sea looks like oil.
#: Matches ``settings.sar_min_wind_speed_ms``; kept as a named constant here
#: so the regional display and the screener cannot drift apart silently.
LOW_WIND_MS = settings.sar_min_wind_speed_ms

TIMEOUT = 30.0
#: Open-Meteo asks for at most a few hundred locations per call. Forty fits
#: comfortably; the chunk exists so adding regions cannot silently break it.
MAX_LOCATIONS_PER_CALL = 100

CACHE_FILE = (
    Path(
        settings.water_cache_dir
        if Path(settings.water_cache_dir).is_absolute()
        else REPO_ROOT / settings.water_cache_dir
    )
    / "open_meteo"
    / "marine_conditions.json"
)


@dataclass(slots=True)
class RegionConditions:
    """Current conditions for one monitored region."""

    cell_code: str
    latitude: float
    longitude: float
    observed_at: str | None
    wind_speed_ms: float | None
    wind_direction_deg: float | None
    wind_gust_ms: float | None
    wave_height_m: float | None
    wave_period_s: float | None
    sea_surface_temp_c: float | None

    @property
    def sar_ambiguous(self) -> bool | None:
        """Whether wind is low enough to make SAR dark formations ambiguous.

        ``None`` when wind is unknown -- which is not the same as "fine".
        """
        if self.wind_speed_ms is None:
            return None
        return self.wind_speed_ms < LOW_WIND_MS

    def to_dict(self) -> dict[str, Any]:
        """Serialise with the provenance a reader needs."""
        return {
            "cell_code": self.cell_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "observed_at": self.observed_at,
            "wind_speed_ms": self.wind_speed_ms,
            "wind_direction_deg": self.wind_direction_deg,
            "wind_gust_ms": self.wind_gust_ms,
            "wave_height_m": self.wave_height_m,
            "wave_period_s": self.wave_period_s,
            "sea_surface_temp_c": self.sea_surface_temp_c,
            "sar_ambiguous": self.sar_ambiguous,
            "low_wind_threshold_ms": LOW_WIND_MS,
            "evidence_level": EVIDENCE_LEVEL,
            "provider": PROVIDER,
            "attribution": ATTRIBUTION,
        }


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    """Split a list into runs of at most ``size``."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _as_list(payload: Any) -> list[dict]:
    """Normalise Open-Meteo's response shape.

    One location returns an object; several return an array. Handling only
    the array form would break the single-region case and only the object
    form would break every other.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [payload] if isinstance(payload, dict) else []


class MarineConditionsClient:
    """Open-Meteo wind and wave conditions for the monitored regions."""

    def __init__(self) -> None:
        """Ensure the cache directory exists."""
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    def fetch(
        self, points: list[tuple[str, float, float]]
    ) -> tuple[list[RegionConditions], str | None]:
        """Fetch current conditions for ``(cell_code, lat, lon)`` points.

        Returns the readings and an error string. A partial failure is
        reported rather than filled in: if the marine endpoint is down, wind
        still arrives and wave fields stay ``None``, which the page renders
        as absent rather than as calm seas.
        """
        if not points:
            return [], None

        wind: dict[str, dict] = {}
        marine: dict[str, dict] = {}
        errors: list[str] = []

        for batch in _chunk(points, MAX_LOCATIONS_PER_CALL):
            lats = ",".join(f"{lat:.4f}" for _, lat, _ in batch)
            lons = ",".join(f"{lon:.4f}" for _, _, lon in batch)
            codes = [code for code, _, _ in batch]

            wind_rows, error = self._call(
                FORECAST_URL,
                {
                    "latitude": lats,
                    "longitude": lons,
                    "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                    "wind_speed_unit": "ms",
                    "timezone": "UTC",
                },
            )
            if error:
                errors.append(f"wind: {error}")
            for code, row in zip(codes, wind_rows, strict=False):
                wind[code] = row.get("current") or {}

            marine_rows, error = self._call(
                MARINE_URL,
                {
                    "latitude": lats,
                    "longitude": lons,
                    "current": "wave_height,wave_period,sea_surface_temperature",
                    "timezone": "UTC",
                },
            )
            if error:
                errors.append(f"marine: {error}")
            for code, row in zip(codes, marine_rows, strict=False):
                marine[code] = row.get("current") or {}

        readings = []
        for code, lat, lon in points:
            w = wind.get(code, {})
            m = marine.get(code, {})
            readings.append(
                RegionConditions(
                    cell_code=code,
                    latitude=lat,
                    longitude=lon,
                    observed_at=w.get("time") or m.get("time"),
                    wind_speed_ms=_number(w.get("wind_speed_10m")),
                    wind_direction_deg=_number(w.get("wind_direction_10m")),
                    wind_gust_ms=_number(w.get("wind_gusts_10m")),
                    wave_height_m=_number(m.get("wave_height")),
                    wave_period_s=_number(m.get("wave_period")),
                    sea_surface_temp_c=_number(m.get("sea_surface_temperature")),
                )
            )
        return readings, "; ".join(errors) or None

    @staticmethod
    def _call(url: str, params: dict[str, Any]) -> tuple[list[dict], str | None]:
        """One Open-Meteo request, returning rows and an error string."""
        try:
            response = httpx.get(url, params=params, timeout=TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            logger.warning("open_meteo_failed", extra={"error": type(exc).__name__})
            return [], type(exc).__name__
        if response.status_code != 200:
            logger.warning(
                "open_meteo_failed", extra={"status": response.status_code}
            )
            return [], f"HTTP {response.status_code}"
        return _as_list(response.json()), None

    def save(self, readings: list[RegionConditions], error: str | None) -> None:
        """Write the cache the API serves from."""
        CACHE_FILE.write_text(
            json.dumps(
                {
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "error": error,
                    "items": [r.to_dict() for r in readings],
                },
                indent=1,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def load() -> dict[str, Any] | None:
        """The cached conditions, or ``None`` if nothing has been fetched."""
        if not CACHE_FILE.exists():
            return None
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def _number(value: Any) -> float | None:
    """A float, or ``None``. Never a zero standing in for a missing value."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_client: MarineConditionsClient | None = None


def get_marine_conditions_client() -> MarineConditionsClient:
    """Process-wide client."""
    global _client
    if _client is None:
        _client = MarineConditionsClient()
    return _client
