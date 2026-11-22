"""Global Fishing Watch: real vessel activity, deliberately without identities.

GFW publishes apparent fishing effort derived from AIS, as hours and vessel
counts on a grid. This module asks for it per monitored region and stores the
aggregate: how many vessels, how many hours, under which flags.

**Why aggregate, and not vessel identities.** GFW can name individual
vessels, and the platform has a table that associates a vessel with a SAR
candidate as ``SOURCE_SUSPECT`` with a confidence score. Those candidates are
research benchmark patches and demonstration events -- no oil was spilled by
anyone. Putting a real MMSI into that association would render a real,
identifiable ship as the named suspect for a spill that did not occur, at a
confidence of 0.97, on a page built to be screenshotted. The existing banner
("do not identify a responsible vessel") is a caveat; a real vessel name
under it is still an accusation.

So the suspect association keeps its clearly-labelled fictional vessels, and
GFW is used for the question it can answer honestly: **how busy is this
water, really**. That is genuinely useful next to a dark-formation detection
-- heavy traffic is context for a slick -- and it implicates nobody.

Attribution is required: "Powered by Global Fishing Watch", linked to
globalfishingwatch.org, wherever this data appears.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Required wherever GFW data is shown, linked to the site.
ATTRIBUTION = "Powered by Global Fishing Watch"
ATTRIBUTION_URL = "https://globalfishingwatch.org"
PROVIDER = "Global Fishing Watch"

#: AIS-derived apparent fishing effort. "Apparent" is GFW's own word: the
#: activity is inferred from vessel movement, not reported by the vessel.
DATASET = "public-global-fishing-effort:latest"
PRODUCT = "GFW apparent fishing effort (AIS-derived)"

#: Derived from recorded AIS transmissions, but the *activity* is a model's
#: inference from a track, so this is INFERRED rather than OBSERVED.
EVIDENCE_LEVEL = "INFERRED"

REPORT_URL = "/4wings/report"
TIMEOUT = 90.0
DEFAULT_WINDOW_DAYS = 45

CACHE_DIR = Path(
    settings.water_cache_dir
    if Path(settings.water_cache_dir).is_absolute()
    else REPO_ROOT / settings.water_cache_dir
) / "gfw"


@dataclass(slots=True)
class RegionActivity:
    """Aggregate vessel activity over one region for one window."""

    cell_code: str
    window_from: str
    window_to: str
    total_hours: float
    vessel_count: int
    grid_cells: int
    #: Hours by flag state, descending. Flags are country codes, not vessels.
    hours_by_flag: dict[str, float] = field(default_factory=dict)

    @property
    def top_flags(self) -> list[tuple[str, float]]:
        """The busiest flag states, heaviest first."""
        return sorted(self.hours_by_flag.items(), key=lambda kv: -kv[1])[:5]

    def to_dict(self) -> dict[str, Any]:
        """Serialise with the attribution GFW requires."""
        return {
            "cell_code": self.cell_code,
            "window_from": self.window_from,
            "window_to": self.window_to,
            "total_hours": round(self.total_hours, 1),
            "vessel_count": self.vessel_count,
            "grid_cells": self.grid_cells,
            "top_flags": [
                {"flag": flag, "hours": round(hours, 1)}
                for flag, hours in self.top_flags
            ],
            "evidence_level": EVIDENCE_LEVEL,
            "dataset": DATASET,
            "product": PRODUCT,
            "provider": PROVIDER,
            "attribution": ATTRIBUTION,
            "attribution_url": ATTRIBUTION_URL,
            "note": (
                "Aggregate activity only. This platform does not attach a "
                "real vessel identity to any detection: the candidates it "
                "holds are research benchmark patches and demonstration "
                "events, and naming a real ship as the source of one would "
                "be an accusation about something that did not happen."
            ),
        }


class GFWClient:
    """Global Fishing Watch 4wings aggregate reports, cached to disk."""

    def __init__(self) -> None:
        """Ensure the cache directory exists."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def is_configured(self) -> bool:
        """True when an API token is present."""
        return bool(settings.gfw_api_token)

    def fetch_region(
        self,
        cell_code: str,
        bbox: tuple[float, float, float, float],
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
        use_cache: bool = True,
        today: date | None = None,
    ) -> RegionActivity | None:
        """Aggregate vessel activity over one region.

        Returns ``None`` when GFW is unreachable or unconfigured. A region
        with no activity returns a reading of **zero**, which is a different
        thing and is stored as such: "no vessels were seen here" is a
        finding, "we could not ask" is not.
        """
        end = today or datetime.now(UTC).date()
        start = end - timedelta(days=window_days)
        cache_file = CACHE_DIR / f"{cell_code}_{start}_{end}.json"

        if use_cache and cache_file.exists():
            try:
                return RegionActivity(**json.loads(cache_file.read_text("utf-8")))
            except (json.JSONDecodeError, TypeError):
                pass

        if not self.is_configured:
            return None

        min_lon, min_lat, max_lon, max_lat = bbox
        body = {
            "geojson": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [min_lon, min_lat],
                        [max_lon, min_lat],
                        [max_lon, max_lat],
                        [min_lon, max_lat],
                        [min_lon, min_lat],
                    ]
                ],
            }
        }
        params = {
            "spatial-resolution": "LOW",
            "temporal-resolution": "ENTIRE",
            "datasets[0]": DATASET,
            "date-range": f"{start.isoformat()},{end.isoformat()}",
            "format": "JSON",
            "group-by": "FLAG",
        }
        try:
            response = httpx.post(
                f"{settings.gfw_api_url.rstrip('/')}{REPORT_URL}",
                headers={"Authorization": f"Bearer {settings.gfw_api_token}"},
                params=params,
                json=body,
                timeout=TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("gfw_report_failed", extra={"error": type(exc).__name__})
            return None
        if response.status_code != 200:
            # The body is not logged: an error can echo the request, and the
            # request carries the token.
            logger.warning("gfw_report_failed", extra={"status": response.status_code})
            return None

        activity = self._parse(cell_code, start, end, response.json())
        cache_file.write_text(
            json.dumps(
                {
                    "cell_code": activity.cell_code,
                    "window_from": activity.window_from,
                    "window_to": activity.window_to,
                    "total_hours": activity.total_hours,
                    "vessel_count": activity.vessel_count,
                    "grid_cells": activity.grid_cells,
                    "hours_by_flag": activity.hours_by_flag,
                }
            ),
            encoding="utf-8",
        )
        return activity

    @staticmethod
    def _parse(
        cell_code: str, start: date, end: date, payload: dict[str, Any]
    ) -> RegionActivity:
        """Sum one 4wings report into a single regional figure.

        The response nests rows under the dataset's *resolved* name, which
        carries a concrete version (``...:v5.0``) rather than the ``:latest``
        that was requested -- so the key is taken from the response rather
        than assumed, or every row would be silently dropped on the next
        version bump.
        """
        rows: list[dict] = []
        for entry in payload.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            for value in entry.values():
                if isinstance(value, list):
                    rows.extend(item for item in value if isinstance(item, dict))

        hours_by_flag: dict[str, float] = {}
        vessels = 0
        cells = 0
        for row in rows:
            hours = float(row.get("hours") or 0.0)
            flag = str(row.get("flag") or "unknown")
            hours_by_flag[flag] = hours_by_flag.get(flag, 0.0) + hours
            vessels += int(row.get("vesselIDs") or 0)
            cells += 1

        return RegionActivity(
            cell_code=cell_code,
            window_from=start.isoformat(),
            window_to=end.isoformat(),
            total_hours=sum(hours_by_flag.values()),
            vessel_count=vessels,
            grid_cells=cells,
            hours_by_flag=hours_by_flag,
        )


_client: GFWClient | None = None


def get_gfw_client() -> GFWClient:
    """Process-wide client."""
    global _client
    if _client is None:
        _client = GFWClient()
    return _client


#: How far around a candidate to summarise vessel activity, and over how long.
#:
#: Thirty kilometres and a week either side of the acquisition. Wide enough
#: that a slick's likely source would fall inside it, narrow enough that the
#: answer still describes *this* water rather than the whole region. These
#: are context, not an investigation: the window is generous on purpose,
#: because a tighter one would invite reading proximity as causation.
CANDIDATE_RADIUS_KM = 30.0
CANDIDATE_WINDOW_DAYS = 7


def candidate_activity(
    client: GFWClient,
    candidate_id: str,
    lat: float,
    lon: float,
    when: datetime,
    *,
    radius_km: float = CANDIDATE_RADIUS_KM,
    window_days: int = CANDIDATE_WINDOW_DAYS,
    use_cache: bool = True,
) -> RegionActivity | None:
    """Aggregate vessel activity around one candidate, in one time window.

    Returns a :class:`RegionActivity` whose ``cell_code`` is the candidate
    id, or ``None`` when GFW could not be reached.

    **No vessel is identified.** Hours and counts by flag state, nothing
    else. This answers "how busy was this water at the time", which is
    context a reviewer can use, and refuses the question it must not answer
    -- which ship did it -- because these candidates are benchmark patches
    and the answer would be an accusation about an event that was never
    established.
    """
    import math

    half = radius_km / 111.32
    half_lon = half / max(math.cos(math.radians(lat)), 0.1)
    bbox = (lon - half_lon, lat - half, lon + half_lon, lat + half)

    centre = when.date()
    end = centre + timedelta(days=window_days)
    return client.fetch_region(
        f"cand_{candidate_id}",
        bbox,
        window_days=window_days * 2,
        use_cache=use_cache,
        today=end,
    )
