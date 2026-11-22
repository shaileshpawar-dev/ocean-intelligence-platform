"""Real Sentinel-2 water-quality indices over the monitored Indian regions.

This is the first module in the marine half of the platform that returns
measurements rather than demonstration data. Everything it reports was
computed by Copernicus from an actual Sentinel-2 acquisition, on a date it
names, and is labelled ``OBSERVED``.

Three indices, each a published band ratio, each measuring something different:

``NDCI`` -- Normalised Difference Chlorophyll Index, ``(B05 - B04) / (B05 +
    B04)``. Mishra & Mishra (2012). Tracks chlorophyll-a, so it responds to
    algal biomass. High values in a coastal bay mean productive or bloom
    conditions.

``NDTI`` -- Normalised Difference Turbidity Index, ``(B04 - B03) / (B04 +
    B03)``. Lacaux et al. (2007). Responds to suspended sediment. River
    plumes and post-monsoon runoff raise it; it says nothing about pollution
    on its own, because the Indian coast is naturally turbid.

``FDI`` -- Floating Debris Index, Biermann et al. (2020), *Scientific
    Reports* 10:5364. ``B08`` minus a baseline interpolated between ``B06``
    and ``B11``. It responds to **anything floating that is brighter in the
    near-infrared than the water around it**.

A word about what FDI is not, because this is the one that invites a wrong
headline. Biermann's own paper separates floating material into plastics,
seaweed, sea-snot, foam, timber and spume, and needs further spectral
analysis to tell them apart -- at 10 m resolution a positive pixel is roughly
a tennis court of *something*. Sargassum, foam lines and sun glint all raise
it. So this module reports "possible floating material" and nothing else.
There is no threshold here above which the platform will call something
plastic, because the measurement cannot support that word.

Only water is measured. The scene classification layer (``SCL``) ships with
every L2A product, and pixels that are not its water class are excluded from
every statistic, so a cell that is mostly coastline reports on the sea in it
rather than on the land.

Every response is cached to disk, keyed by cell and window. A demo makes no
live call.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Copernicus asks that products carry this notice. Rendered wherever an
#: index derived from these scenes is shown.
COPERNICUS_ATTRIBUTION = "Contains modified Copernicus Sentinel data {year}"

#: What a positive FDI is allowed to be called. Not configurable, and not a
#: display string the UI may override -- see the module docstring.
FDI_LABEL = "possible floating material"

#: Sentinel-2 band centres (nm) used for the FDI baseline interpolation.
_LAMBDA_NIR = 832.8  # B08
_LAMBDA_RED = 664.6  # B04
_LAMBDA_SWIR1 = 1613.7  # B11
#: Biermann's baseline slope, ((NIR - RED) / (SWIR1 - RED)) * 10.
FDI_SLOPE = ((_LAMBDA_NIR - _LAMBDA_RED) / (_LAMBDA_SWIR1 - _LAMBDA_RED)) * 10

#: SCL class 6 is "water". The others are land, cloud, shadow, snow, defect.
SCL_WATER = 6

#: Water pixels below which a reading describes a puddle, not a region.
#:
#: The first full sweep produced readings computed from as few as **one**
#: water pixel -- a cell almost entirely under cloud, with a single clear gap.
#: Those statistics are arithmetically valid and completely meaningless, and
#: one of them (FDI -0.2084 from 8 pixels) was an order of magnitude from
#: every other cell, which is exactly the sort of figure that becomes a
#: story. At 1 km per pixel this floor is 100 km2 of observed sea.
#:
#: Such readings are stored rather than dropped -- "the satellite saw almost
#: no water here" is itself worth keeping -- but they are marked, and the API
#: and the page say so rather than printing the number plainly.
MIN_WATER_PIXELS = 100

DEFAULT_WINDOW_DAYS = 30
DEFAULT_MAX_CLOUD_PCT = 30

#: Sentinel Hub refuses an S2L2A request coarser than 1500 m per pixel. A
#: fixed grid cannot satisfy that across these cells: the Gulf of Kutch is
#: 0.3 degrees across and Bay of Bengal Z3 is four, so 100x100 is 330 m on
#: one and 4,449 m on the other -- which is exactly how the first run failed,
#: on 31 of 40 cells. The grid is therefore derived from the cell.
MAX_METRES_PER_PIXEL = 1500.0
#: Target resolution, comfortably inside the limit.
TARGET_METRES_PER_PIXEL = 1000.0
#: Bounds on the derived grid. The floor keeps a tiny cell from being
#: sampled at a handful of pixels; the ceiling keeps a large one cheap. This
#: is a regional index, not a map.
MIN_GRID = 50
MAX_GRID = 1000

_METRES_PER_DEGREE = 111_320.0

TOKEN_TIMEOUT = 30.0
STATS_TIMEOUT = 120.0
#: The API rate-limits a sustained sweep. Retried, with a widening pause.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_BACKOFF_SECONDS = 8.0


def grid_for(bbox: tuple[float, float, float, float]) -> tuple[int, int]:
    """Pixel dimensions for one bbox, respecting the resolution limit.

    Returns ``(width, height)``. Longitude degrees shrink with latitude, so
    the east-west span is scaled by ``cos(mean latitude)``; ignoring that
    would over-state the width of every cell and waste resolution.
    """
    import math

    min_lon, min_lat, max_lon, max_lat = bbox
    mean_lat = math.radians((min_lat + max_lat) / 2)
    width_m = abs(max_lon - min_lon) * _METRES_PER_DEGREE * math.cos(mean_lat)
    height_m = abs(max_lat - min_lat) * _METRES_PER_DEGREE

    def axis(span_m: float) -> int:
        pixels = int(math.ceil(span_m / TARGET_METRES_PER_PIXEL))
        pixels = max(MIN_GRID, min(MAX_GRID, pixels))
        # The clamp can still leave a huge cell too coarse, so enforce the
        # hard limit last: it is the one the API actually checks.
        if span_m / pixels > MAX_METRES_PER_PIXEL:
            pixels = int(math.ceil(span_m / MAX_METRES_PER_PIXEL))
        return max(1, pixels)

    return axis(width_m), axis(height_m)

CACHE_DIR = Path(
    settings.water_cache_dir
    if Path(settings.water_cache_dir).is_absolute()
    else REPO_ROOT / settings.water_cache_dir
) / "sentinel2"


EVALSCRIPT = """//VERSION=3
// Water-only NDCI, NDTI and FDI. Non-water pixels are removed from every
// statistic through dataMask, so a coastal cell reports on its sea.
function setup() {
  return {
    input: [{ bands: ["B03","B04","B05","B06","B08","B11","SCL","dataMask"] }],
    output: [
      { id: "ndci", bands: 1, sampleType: "FLOAT32" },
      { id: "ndti", bands: 1, sampleType: "FLOAT32" },
      { id: "fdi",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  var isWater = (s.SCL === %(water)d) ? 1 : 0;
  var ndci = (s.B05 + s.B04) > 0 ? (s.B05 - s.B04) / (s.B05 + s.B04) : 0;
  var ndti = (s.B04 + s.B03) > 0 ? (s.B04 - s.B03) / (s.B04 + s.B03) : 0;
  // Biermann et al. (2020): NIR minus a baseline interpolated from the
  // red-edge and SWIR bands.
  var baseline = s.B06 + (s.B11 - s.B06) * %(slope).4f;
  var fdi = s.B08 - baseline;
  return {
    ndci: [ndci],
    ndti: [ndti],
    fdi: [fdi],
    dataMask: [s.dataMask * isWater]
  };
}
""" % {"water": SCL_WATER, "slope": FDI_SLOPE}


@dataclass(slots=True)
class IndexReading:
    """One cell's indices from one Sentinel-2 acquisition date."""

    cell_code: str
    observed_on: date
    ndci_mean: float
    ndci_p50: float
    ndti_mean: float
    ndti_p50: float
    fdi_mean: float
    fdi_p90: float
    #: Water pixels the statistics were computed from, and the grid total.
    water_pixels: int
    total_pixels: int
    max_cloud_pct: int
    evidence_level: str = "OBSERVED"
    source: str = "Copernicus Sentinel-2 L2A (Sentinel Hub Statistics API)"

    @property
    def water_fraction(self) -> float:
        """Share of the sampled grid that was classified as water."""
        return self.water_pixels / self.total_pixels if self.total_pixels else 0.0

    @property
    def attribution(self) -> str:
        """The notice Copernicus asks products to carry."""
        return COPERNICUS_ATTRIBUTION.format(year=self.observed_on.year)

    @property
    def characterises_region(self) -> bool:
        """Whether enough sea was in frame for the indices to mean anything."""
        return self.water_pixels >= MIN_WATER_PIXELS

    @property
    def caveat(self) -> str | None:
        """Why this reading should not be read as a regional value, if so."""
        if self.characterises_region:
            return None
        return (
            f"Computed from {self.water_pixels} water pixel"
            f"{'' if self.water_pixels == 1 else 's'} of "
            f"{self.total_pixels:,} sampled: the cell was almost entirely "
            "land or cloud on this pass. Recorded for completeness; too "
            "little sea was observed for these values to describe the region."
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the API, carrying its own provenance."""
        return {
            "cell_code": self.cell_code,
            "observed_on": self.observed_on.isoformat(),
            "ndci_mean": round(self.ndci_mean, 4),
            "ndci_p50": round(self.ndci_p50, 4),
            "ndti_mean": round(self.ndti_mean, 4),
            "ndti_p50": round(self.ndti_p50, 4),
            "fdi_mean": round(self.fdi_mean, 5),
            "fdi_p90": round(self.fdi_p90, 5),
            "fdi_label": FDI_LABEL,
            "water_pixels": self.water_pixels,
            "total_pixels": self.total_pixels,
            "water_fraction": round(self.water_fraction, 3),
            "max_cloud_pct": self.max_cloud_pct,
            "evidence_level": self.evidence_level,
            "source": self.source,
            "attribution": self.attribution,
            "characterises_region": self.characterises_region,
            "caveat": self.caveat,
        }


@dataclass(slots=True)
class FetchOutcome:
    """What a fetch produced, including the honest empty cases."""

    status: str  # "ok" | "no_acquisition" | "unconfigured" | "error"
    readings: list[IndexReading] = field(default_factory=list)
    detail: str | None = None
    from_cache: bool = False


class Sentinel2IndexClient:
    """Sentinel Hub Statistics API, authenticated with client credentials.

    The password grant that drives the STAC catalogue is rejected by Sentinel
    Hub; the OAuth client pair is what it accepts. Verified 21 Nov 2026.
    """

    def __init__(self) -> None:
        """Prepare the cache directory and an empty token."""
        self._token: str | None = None
        self._expires_at: float = 0.0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def is_configured(self) -> bool:
        """True when an OAuth client pair is present."""
        return bool(settings.cdse_client_id and settings.cdse_client_secret)

    def _get_token(self) -> str | None:
        """A cached bearer token, refreshed a minute before it expires."""
        if not self.is_configured:
            return None
        now = time.time()
        if self._token and now < self._expires_at - 60:
            return self._token
        try:
            response = httpx.post(
                settings.cdse_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.cdse_client_id,
                    "client_secret": settings.cdse_client_secret,
                },
                timeout=TOKEN_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cdse_token_failed", extra={"error": type(exc).__name__})
            return None
        if response.status_code != 200:
            # The body is not logged: a token error can quote the request,
            # and the request carries the client secret.
            logger.warning("cdse_token_failed", extra={"status": response.status_code})
            return None
        payload = response.json()
        self._token = payload.get("access_token")
        self._expires_at = now + payload.get("expires_in", 600)
        return self._token

    def _cache_path(
        self, cell_code: str, start: date, end: date, max_cloud: int
    ) -> Path:
        """Disk location for one cell-window response."""
        key = f"{cell_code}|{start}|{end}|{max_cloud}|derived-grid"
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return CACHE_DIR / f"{cell_code}_{digest}.json"

    def fetch_cell(
        self,
        cell_code: str,
        bbox: tuple[float, float, float, float],
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
        max_cloud_pct: int = DEFAULT_MAX_CLOUD_PCT,
        use_cache: bool = True,
        today: date | None = None,
    ) -> FetchOutcome:
        """Indices for one grid cell, one reading per acquisition date.

        Aggregated per day rather than over the whole window, so each reading
        carries the date it was actually measured on. A 30-day mean would be
        a number with no moment attached, which the freshness engine could
        not reason about and a reader could not check.
        """
        end = today or datetime.now(UTC).date()
        start = end - timedelta(days=window_days)
        cache_file = self._cache_path(cell_code, start, end, max_cloud_pct)

        payload: dict[str, Any] | None = None
        from_cache = False
        if use_cache and cache_file.exists():
            try:
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
                from_cache = True
            except json.JSONDecodeError:
                payload = None

        if payload is None:
            if not self.is_configured:
                return FetchOutcome(
                    status="unconfigured",
                    detail=(
                        "CDSE_CLIENT_ID and CDSE_CLIENT_SECRET are not set, so "
                        "no Sentinel-2 scene can be requested. No substitute "
                        "value is produced."
                    ),
                )
            token = self._get_token()
            if not token:
                return FetchOutcome(
                    status="error", detail="Could not obtain a CDSE access token."
                )
            body = self._request_body(bbox, start, end, max_cloud_pct)
            response = None
            for attempt in range(1, RATE_LIMIT_RETRIES + 1):
                try:
                    response = httpx.post(
                        settings.cdse_statistics_url,
                        headers={"Authorization": f"Bearer {token}"},
                        json=body,
                        timeout=STATS_TIMEOUT,
                    )
                except Exception as exc:  # noqa: BLE001
                    return FetchOutcome(status="error", detail=type(exc).__name__)
                if response.status_code != 429:
                    break
                # Sweeping 40 cells in a row trips the quota. Waiting is the
                # correct response to a 429; retrying immediately is not.
                if attempt < RATE_LIMIT_RETRIES:
                    time.sleep(RATE_LIMIT_BACKOFF_SECONDS * attempt)

            assert response is not None
            if response.status_code != 200:
                detail = f"Statistics API returned HTTP {response.status_code}"
                try:
                    message = (response.json().get("error") or {}).get("message")
                    if message:
                        detail = f"{detail}: {message[:180]}"
                except Exception:  # noqa: BLE001
                    pass
                return FetchOutcome(status="error", detail=detail)
            payload = response.json()
            cache_file.write_text(json.dumps(payload), encoding="utf-8")

        readings = self._parse(cell_code, payload, max_cloud_pct)
        if not readings:
            return FetchOutcome(
                status="no_acquisition",
                from_cache=from_cache,
                detail=(
                    f"No Sentinel-2 acquisition over {cell_code} in the last "
                    f"{window_days} days cleared {max_cloud_pct}% cloud with "
                    "water pixels in frame."
                ),
            )
        return FetchOutcome(status="ok", readings=readings, from_cache=from_cache)

    @staticmethod
    def _request_body(
        bbox: tuple[float, float, float, float],
        start: date,
        end: date,
        max_cloud_pct: int,
    ) -> dict[str, Any]:
        """The Statistics API request for one cell."""
        width, height = grid_for(bbox)
        return {
            "input": {
                "bounds": {
                    "bbox": list(bbox),
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    },
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {"maxCloudCoverage": max_cloud_pct},
                    }
                ],
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start.isoformat()}T00:00:00Z",
                    "to": f"{end.isoformat()}T23:59:59Z",
                },
                # One interval per day: each reading keeps its own date.
                "aggregationInterval": {"of": "P1D"},
                "width": width,
                "height": height,
                "evalscript": EVALSCRIPT,
            },
            "calculations": {
                "ndci": {"statistics": {"default": {"percentiles": {"k": [50]}}}},
                "ndti": {"statistics": {"default": {"percentiles": {"k": [50]}}}},
                "fdi": {"statistics": {"default": {"percentiles": {"k": [90]}}}},
            },
        }

    @staticmethod
    def _parse(
        cell_code: str, payload: dict[str, Any], max_cloud_pct: int
    ) -> list[IndexReading]:
        """Turn the Statistics response into readings, skipping empty days.

        An interval with no water pixels is dropped rather than recorded as a
        zero. Sentinel-2 revisits every few days and most intervals in a
        window are simply days the satellite did not look, or looked through
        cloud; writing those down as measurements of zero chlorophyll would
        be the single most misleading thing this module could do.
        """
        readings: list[IndexReading] = []
        for interval in payload.get("data") or []:
            outputs = interval.get("outputs") or {}
            try:
                ndci = outputs["ndci"]["bands"]["B0"]["stats"]
                ndti = outputs["ndti"]["bands"]["B0"]["stats"]
                fdi = outputs["fdi"]["bands"]["B0"]["stats"]
            except (KeyError, TypeError):
                continue

            sample_count = int(ndci.get("sampleCount") or 0)
            no_data = int(ndci.get("noDataCount") or 0)
            water_pixels = sample_count - no_data
            if water_pixels <= 0:
                continue

            day = (interval.get("interval") or {}).get("from", "")[:10]
            try:
                observed_on = date.fromisoformat(day)
            except ValueError:
                continue

            readings.append(
                IndexReading(
                    cell_code=cell_code,
                    observed_on=observed_on,
                    ndci_mean=float(ndci.get("mean") or 0.0),
                    ndci_p50=float((ndci.get("percentiles") or {}).get("50.0") or 0.0),
                    ndti_mean=float(ndti.get("mean") or 0.0),
                    ndti_p50=float((ndti.get("percentiles") or {}).get("50.0") or 0.0),
                    fdi_mean=float(fdi.get("mean") or 0.0),
                    fdi_p90=float((fdi.get("percentiles") or {}).get("90.0") or 0.0),
                    water_pixels=water_pixels,
                    total_pixels=sample_count,
                    max_cloud_pct=max_cloud_pct,
                )
            )
        readings.sort(key=lambda r: r.observed_on, reverse=True)
        return readings


    def fetch_thumbnail(
        self,
        cell_code: str,
        bbox: tuple[float, float, float, float],
        observed_on: date,
        *,
        use_cache: bool = True,
    ) -> Path | None:
        """A true-colour PNG of one cell on one acquisition date.

        Returned as a file on disk, cached, so the page shows the scene the
        indices were computed from rather than a stock image of the sea. The
        day is pinned to the reading's own date: a thumbnail from a different
        pass would illustrate nothing.

        Dimensions come from :func:`grid_for`, the same derivation the
        statistics use, rather than a fixed square. A fixed 320x320 is 330 m
        per pixel on the Gulf of Kutch and 14 km on Arabian Sea Z5, and the
        Process API refuses the latter for exactly the reason the Statistics
        API did -- which is why those two cells had no thumbnail while the
        other 33 did.
        """
        width, height = grid_for(bbox)
        target = CACHE_DIR / "thumbs" / f"{cell_code}_{observed_on.isoformat()}.png"
        if use_cache and target.exists() and target.stat().st_size > 0:
            return target
        if not self.is_configured:
            return None
        token = self._get_token()
        if not token:
            return None

        evalscript = """//VERSION=3
function setup() {
  return { input: ["B04","B03","B02"], output: { bands: 3 } };
}
function evaluatePixel(s) {
  // 3.5x gain: raw L2A reflectance over water is very dark, and an
  // unstretched thumbnail reads as a black square.
  return [s.B04 * 3.5, s.B03 * 3.5, s.B02 * 3.5];
}
"""
        body = {
            "input": {
                "bounds": {
                    "bbox": list(bbox),
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    },
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {
                                "from": f"{observed_on.isoformat()}T00:00:00Z",
                                "to": f"{observed_on.isoformat()}T23:59:59Z",
                            }
                        },
                    }
                ],
            },
            "output": {
                "width": width,
                "height": height,
                "responses": [
                    {"identifier": "default", "format": {"type": "image/png"}}
                ],
            },
            "evalscript": evalscript,
        }
        try:
            response = httpx.post(
                settings.cdse_process_url,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                timeout=STATS_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("s2_thumb_failed", extra={"error": type(exc).__name__})
            return None
        if response.status_code != 200 or not response.content:
            logger.warning("s2_thumb_failed", extra={"status": response.status_code})
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target


_client: Sentinel2IndexClient | None = None


def get_sentinel2_client() -> Sentinel2IndexClient:
    """Process-wide client, so the bearer token is shared."""
    global _client
    if _client is None:
        _client = Sentinel2IndexClient()
    return _client
