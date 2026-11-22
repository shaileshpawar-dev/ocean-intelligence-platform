r"""Replay a documented oil-spill incident through the SAR detector.

The platform's SAR classifier has never been shown a real spill in Indian
waters. Screening ordinary water and finding nothing is weak evidence: a
detector that always says "no" would behave identically. This takes an
incident that is known to have happened, with a position and a date from an
official source, and asks the same pipeline the same question over the days
that followed.

**The incident.** MSC ELSA 3 (IMO 9123221, Liberia flag) sank at 07:50 on
25 May 2025 in position 09°18.75'N 076°08.16'E, about 13 nautical miles
south-west of Kochi, Kerala, carrying roughly 367 tonnes of heavy fuel oil
and 84.4 tonnes of diesel. The Indian Coast Guard reported signs of an oil
spill in the vicinity and conducted dispersant operations.

Source: Kerala State Disaster Management Authority, "SITREP - 3, 1300 Hrs on
25/05/2025, Sinking of MSC ELSA III (IMO no - 9123221, Flag Liberia) 13 nm
South West of Kochi". Position, time, IMO number and fuel quantities are
quoted from that document.

**What this can and cannot establish.** A positive here would be real
evidence the pipeline can find a known slick. A negative is weaker: Sentinel-1
revisits every few days, dispersant was applied, oil weathers and disperses,
and the model is still being applied outside the distribution it was measured
on. So a negative is recorded as what it is -- the detector did not flag the
site on the passes available -- and not as evidence that nothing was there.

Nothing here writes a pollution event on its own. The caller decides, from
the output, whether a genuine detection occurred.

Usage:
    python scripts/replay_incident.py
    python scripts/replay_incident.py --days 14 --radius-km 15
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

_spec = importlib.util.spec_from_file_location(
    "screen_sentinel1", Path(__file__).with_name("screen_sentinel1.py")
)
_s1 = importlib.util.module_from_spec(_spec)
sys.modules["screen_sentinel1"] = _s1
_spec.loader.exec_module(_s1)

from PIL import Image  # noqa: E402

from app.models.enums import PollutionSignature  # noqa: E402
from app.vision.registry import get_sar_v2_2_detector  # noqa: E402
from app.vision.sentinel2_indices import get_sentinel2_client  # noqa: E402

#: Everything below is quoted from the Kerala SDMA situation report.
INCIDENT = {
    "name": "MSC ELSA 3",
    "imo": "9123221",
    "flag": "Liberia",
    "sank_at": "2025-05-25T07:50:00Z",
    "latitude": 9 + 18.75 / 60,  # 09 Deg 18.75 N
    "longitude": 76 + 8.16 / 60,  # 076 Deg 08.16 E
    "position_text": "09°18.75'N 076°08.16'E",
    "distance_text": "13 nautical miles south-west of Kochi, Kerala",
    "cargo_text": (
        "approximately 367 tonnes of heavy fuel oil and 84.4 tonnes of diesel"
    ),
    "citation": (
        "Kerala State Disaster Management Authority, \"SITREP - 3, 1300 Hrs "
        "on 25/05/2025, Sinking of MSC ELSA III (IMO no - 9123221, Flag "
        "Liberia) 13 nm South West of Kochi\". "
        "https://sdma.kerala.gov.in/wp-content/uploads/2025/06/"
        "MSC-ELSA3-SITREP-3-1300-hrs-25052025.pdf"
    ),
    "region_code": "malabar_coast_s",
}

#: Degrees of latitude per kilometre. Longitude is scaled by cos(lat).
_DEG_PER_KM = 1.0 / 111.32


def tiles_around(
    lat: float, lon: float, radius_km: float, tile_deg: float
) -> list[tuple[float, float, float, float]]:
    """A grid of tiles covering a box of ``radius_km`` around a point."""
    dlat = radius_km * _DEG_PER_KM
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    boxes: list[tuple[float, float, float, float]] = []
    steps = max(1, int(math.ceil((2 * dlat) / tile_deg)))
    for row in range(steps):
        for col in range(steps):
            min_lat = lat - dlat + row * tile_deg
            min_lon = lon - dlon + col * tile_deg
            boxes.append(
                (min_lon, min_lat, min_lon + tile_deg, min_lat + tile_deg)
            )
    return boxes


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, good enough at these scales."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def wind_at(lat: float, lon: float, when: date) -> dict | None:
    """ERA5 reanalysis wind for the acquisition, via the existing service.

    Wind is not decoration here. Below roughly 3 m/s the sea goes flat and a
    calm patch is indistinguishable from oil; above roughly 10-12 m/s wind
    roughening erases a slick's contrast entirely. Either one changes what a
    negative result means.
    """
    try:
        from app.vision.era5_client import ERA5Service

        record = ERA5Service().collocate_patch(
            f"replay_{lat:.3f}_{lon:.3f}_{when}",
            lat,
            lon,
            f"{when.isoformat()}T06:00:00",
        )
        payload = record.to_dict()
        return {
            "wind_speed_ms": payload.get("wind_speed_ms"),
            "source": payload.get("source"),
            "quality": payload.get("quality_status"),
        }
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str]) -> int:
    """Screen the days after the incident and report what was found."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--radius-km", type=float, default=15.0)
    parser.add_argument("--max-tiles-per-pass", type=int, default=9)
    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Write the result and a scene thumbnail to the cache the "
            "Real Observations page reads."
        ),
    )
    args = parser.parse_args(argv[1:])

    detector = get_sar_v2_2_detector()
    if not getattr(detector, "is_available", False):
        print("The v2.2 detector is unavailable. Nothing screened.")
        return 1
    token = get_sentinel2_client()._get_token()
    if not token:
        print("No CDSE token. Nothing screened.")
        return 1

    sank = datetime.fromisoformat(INCIDENT["sank_at"].replace("Z", "+00:00"))
    lat, lon = INCIDENT["latitude"], INCIDENT["longitude"]
    window_end = sank.date() + timedelta(days=args.days)

    print(f"Historical incident replay: {INCIDENT['name']}, {sank.date()}")
    print(f"  {INCIDENT['position_text']} ({INCIDENT['distance_text']})")
    print(f"  {INCIDENT['cargo_text']}")
    print(f"  Source: {INCIDENT['citation'][:96]}...")
    print(
        f"\nScreening Sentinel-1 within {args.radius_km:.0f} km for "
        f"{args.days} days after the sinking.\n"
    )

    half = args.radius_km * _DEG_PER_KM
    search_box = (
        lon - half / math.cos(math.radians(lat)),
        lat - half,
        lon + half / math.cos(math.radians(lat)),
        lat + half,
    )

    # Scenes intersecting the wreck site in the fortnight after it sank.
    import httpx

    response = httpx.post(
        _s1.CATALOG_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "bbox": list(search_box),
            "datetime": (
                f"{sank.date().isoformat()}T00:00:00Z/"
                f"{window_end.isoformat()}T23:59:59Z"
            ),
            "collections": ["sentinel-1-grd"],
            "limit": 40,
        },
        timeout=60.0,
    )
    scenes = response.json().get("features", []) if response.status_code == 200 else []
    by_day: dict[str, dict] = {}
    for scene in scenes:
        day = scene["properties"]["datetime"][:10]
        by_day.setdefault(day, scene)

    if not by_day:
        print("No Sentinel-1 acquisition covers the site in this window.")
        print("Recorded as: no coverage. Not as a negative detection.")
        return 0

    print(f"{len(by_day)} Sentinel-1 pass(es) over the site:\n")

    overall_max = 0.0
    overall_max_at: tuple[float, float] | None = None
    passes: list[dict] = []
    flagged: list[dict] = []
    total_screened = 0
    tile_stats: list[dict] = []

    for day in sorted(by_day):
        screened = 0
        day_max = 0.0
        day_flagged = 0
        for box in tiles_around(lat, lon, args.radius_km, _s1.TILE_DEG):
            if screened >= args.max_tiles_per_pass:
                break
            array = _s1.fetch_tile(token, box, day)
            if array is None:
                continue
            screened += 1
            total_screened += 1
            tile_stats.append(_s1.tile_statistics(array))

            detections = detector.predict(Image.fromarray(array, mode="L"))
            for detection in detections:
                probability = detection.extra.get("p_oil_candidate", 0.0)
                day_max = max(day_max, probability)
                centre = ((box[1] + box[3]) / 2, (box[0] + box[2]) / 2)
                if probability > overall_max:
                    overall_max, overall_max_at = probability, centre
                if detection.signature != PollutionSignature.NO_ANOMALY:
                    day_flagged += 1
                    flagged.append(
                        {
                            "day": day,
                            "p_oil": probability,
                            "lat": centre[0],
                            "lon": centre[1],
                            "km_from_wreck": distance_km(lat, lon, *centre),
                        }
                    )

        wind = wind_at(lat, lon, date.fromisoformat(day))
        wind_text = (
            f"wind {wind['wind_speed_ms']:.1f} m/s"
            if wind and wind.get("wind_speed_ms") is not None
            else "wind unknown"
        )
        offset = (date.fromisoformat(day) - sank.date()).days
        passes.append(
            {
                "day": day,
                "days_after": offset,
                "tiles": screened,
                "max_p_oil": round(day_max, 4),
                "flagged": day_flagged,
                "wind_speed_ms": (wind or {}).get("wind_speed_ms"),
                "wind_source": (wind or {}).get("source"),
            }
        )
        print(
            f"  {day}  (+{offset:2d}d)  {screened:2d} tiles  "
            f"max p_oil {day_max:.4f}  {day_flagged} flagged  {wind_text}"
        )

    print(f"\n{total_screened} tiles screened across {len(by_day)} pass(es).")
    if tile_stats:
        mean_of_means = sum(t["mean"] for t in tile_stats) / len(tile_stats)
        print(
            f"Prepared tiles: mean {mean_of_means:.1f} "
            f"(training {_s1.TRAINING_PROFILE['mean']:.0f})."
        )

    if flagged:
        nearest = min(flagged, key=lambda f: f["km_from_wreck"])
        print(f"\n{len(flagged)} tile(s) flagged as oil-like. Nearest to the wreck:")
        print(
            f"  {nearest['day']}  p_oil {nearest['p_oil']:.4f}  "
            f"{nearest['km_from_wreck']:.1f} km from the reported position"
        )
        print("\nThis is a candidate for an incident-replay event.")
    else:
        print(
            f"\nNothing flagged. Highest p_oil anywhere was {overall_max:.4f}"
            + (
                f" at {overall_max_at[0]:.3f}, {overall_max_at[1]:.3f}"
                if overall_max_at
                else ""
            )
        )
        print(
            "\nRecorded as a negative result, which is weaker evidence than a\n"
            "positive would have been: dispersant was applied, oil weathers\n"
            "within days, Sentinel-1 revisits every few days, and the model is\n"
            "still outside the distribution it was measured on. It does not\n"
            "establish that no slick was present."
        )
    if args.save:
        _save(
            total_screened,
            sorted(by_day),
            overall_max,
            overall_max_at,
            flagged,
            tile_stats,
            passes,
            token,
        )
    return 0


#: Where the result and its thumbnail live, alongside the other caches.
RESULT_DIR = Path(_s1.CACHE_DIR).parent / "incident_replay"


def _save(
    screened: int,
    days: list[str],
    overall_max: float,
    overall_max_at: tuple[float, float] | None,
    flagged: list[dict],
    tile_stats: list[dict],
    passes: list[dict],
    token: str,
) -> None:
    """Persist the replay so the application can show it.

    Written whatever the outcome. A negative result is the finding here, and
    a finding that only gets stored when it is favourable is not a finding.
    """
    import json

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    lat, lon = INCIDENT["latitude"], INCIDENT["longitude"]

    thumbnail = None
    if days:
        half = _s1.TILE_DEG / 2
        box = (lon - half, lat - half, lon + half, lat + half)
        array = _s1.fetch_tile(token, box, days[0])
        if array is not None:
            target = RESULT_DIR / f"{INCIDENT['name'].replace(' ', '_')}_{days[0]}.png"
            Image.fromarray(array, mode="L").save(target)
            thumbnail = target.name

    payload = {
        "incident": {
            key: INCIDENT[key]
            for key in (
                "name",
                "imo",
                "flag",
                "sank_at",
                "latitude",
                "longitude",
                "position_text",
                "distance_text",
                "cargo_text",
                "citation",
                "region_code",
            )
        },
        "label": (
            f"Historical incident replay: {INCIDENT['name']}, "
            f"{INCIDENT['sank_at'][:10]}"
        ),
        "screening": {
            "tiles_screened": screened,
            "passes": passes,
            "pass_days": days,
            "max_p_oil": round(overall_max, 4),
            "max_p_oil_at": (
                {"lat": round(overall_max_at[0], 4), "lon": round(overall_max_at[1], 4)}
                if overall_max_at
                else None
            ),
            "flagged_tiles": len(flagged),
            "detected": bool(flagged),
            "prepared_tile_mean": (
                round(sum(t["mean"] for t in tile_stats) / len(tile_stats), 1)
                if tile_stats
                else None
            ),
            "training_tile_mean": _s1.TRAINING_PROFILE["mean"],
            "model": "sar-oil-slick-v2.2",
            "window": "-30..-5 dB fixed, 98% validity floor",
        },
        "thumbnail": thumbnail,
        "verdict": (
            "Detected"
            if flagged
            else "Not detected on the passes available"
        ),
        "interpretation": (
            "The detector did not flag the site on any Sentinel-1 pass in "
            "this window. That is weaker evidence than a positive would "
            "have been: dispersant was applied, oil weathers within days, "
            "the earliest pass was three days after the sinking, and the "
            "model is still being applied outside the distribution it was "
            "measured on. It does not establish that no slick was present."
        )
        if not flagged
        else (
            "The detector flagged tiles near the reported position. See the "
            "event raised for this replay."
        ),
    }
    (RESULT_DIR / "msc_elsa_3.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    print(f"\nSaved to {RESULT_DIR / 'msc_elsa_3.json'}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
