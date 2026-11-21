"""Real Sentinel-2 water-quality indices, per monitored region.

Serves stored rows only. No endpoint here calls Copernicus: fetching is a
job (``scripts/fetch_sentinel2_indices.py``), so a page load cannot be made
slow by a satellite API, and the demo runs from the database.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Region
from app.models.optical import OpticalIndexObservation
from app.vision.cmems_client import (
    ATTRIBUTION as CMEMS_ATTRIBUTION,
)
from app.vision.cmems_client import (
    CHLOROPHYLL_EVIDENCE,
    CHLOROPHYLL_PRODUCT,
    CACHE_DIR as CMEMS_CACHE_DIR,
)
from app.vision.gfw_client import (
    ATTRIBUTION as GFW_ATTRIBUTION,
)
from app.vision.gfw_client import (
    ATTRIBUTION_URL as GFW_ATTRIBUTION_URL,
)
from app.vision.gfw_client import (
    CACHE_DIR as GFW_CACHE_DIR,
)
from app.vision.gfw_client import (
    EVIDENCE_LEVEL as GFW_EVIDENCE_LEVEL,
)
from app.vision.gfw_client import (
    PRODUCT as GFW_PRODUCT,
)
from app.vision.gfw_client import (
    PROVIDER as GFW_PROVIDER,
)
from app.vision.gfw_client import RegionActivity
from app.vision.marine_conditions import ATTRIBUTION as MARINE_ATTRIBUTION
from app.vision.marine_conditions import EVIDENCE_LEVEL as MARINE_EVIDENCE_LEVEL
from app.vision.marine_conditions import LOW_WIND_MS
from app.vision.marine_conditions import PROVIDER as MARINE_PROVIDER
from app.vision.marine_conditions import MarineConditionsClient
from app.vision.sentinel2_indices import (
    CACHE_DIR,
    COPERNICUS_ATTRIBUTION,
    FDI_LABEL,
    MIN_WATER_PIXELS,
)

router = APIRouter(tags=["optical"])

#: What each index is, said once, where the numbers are served. A reader who
#: has never met NDCI should not have to guess from the column header.
INDEX_NOTES = {
    "ndci": {
        "name": "Normalised Difference Chlorophyll Index",
        "formula": "(B05 - B04) / (B05 + B04)",
        "reference": "Mishra & Mishra (2012)",
        "means": (
            "Responds to chlorophyll-a, so it rises with algal biomass. "
            "Productive coastal water reads higher than clear offshore water."
        ),
    },
    "ndti": {
        "name": "Normalised Difference Turbidity Index",
        "formula": "(B04 - B03) / (B04 + B03)",
        "reference": "Lacaux et al. (2007)",
        "means": (
            "Responds to suspended sediment. River plumes and post-monsoon "
            "runoff raise it. On its own it is not a pollution signal -- much "
            "of the Indian coast is naturally turbid."
        ),
    },
    "fdi": {
        "name": "Floating Debris Index",
        "formula": "B08 - (B06 + (B11 - B06) * 1.7722)",
        "reference": "Biermann et al. (2020), Scientific Reports 10:5364",
        "means": (
            f"Responds to {FDI_LABEL} -- anything floating that is brighter "
            "in the near-infrared than the surrounding water. Biermann's own "
            "paper separates floating material into plastics, seaweed, foam, "
            "timber and spume, and needs further spectral analysis to tell "
            "them apart. Sargassum, foam lines and sun glint all raise it. "
            "A positive value here is not evidence of plastic, and this "
            "platform does not use that word for it."
        ),
    },
}


def _chlorophyll_for(region_code: str) -> dict | None:
    """The cached CMEMS chlorophyll reading for a region, if one exists.

    Read straight from the fetch job's cache rather than the database: it is
    a cross-check shown beside NDCI, not a measurement this platform claims
    to have made, and giving it a table would overstate its standing here.
    """
    matches = sorted(CMEMS_CACHE_DIR.glob(f"chl_{region_code}_*.json"), reverse=True)
    for path in matches:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        return {
            "chl_mg_m3": round(float(payload["chl_mg_m3"]), 4),
            "valid_on": payload["valid_on"],
            "valid_pixels": payload.get("valid_pixels"),
            "evidence_level": CHLOROPHYLL_EVIDENCE,
            "product": CHLOROPHYLL_PRODUCT,
            "attribution": CMEMS_ATTRIBUTION,
            "note": (
                "An independent chlorophyll-a retrieval from Copernicus "
                "Marine, shown beside this platform's own NDCI. The two "
                "estimate the same quantity by different routes: NDCI is a "
                "two-band ratio computed here from raw reflectance, this is "
                "a validated multi-sensor product. Neither is adjusted to "
                "agree with the other -- where they disagree, that is the "
                "useful part."
            ),
        }
    return None


def _has_thumbnail(region_code: str, observed_on: str) -> bool:
    """Whether a cached scene image exists for this reading.

    Reported so the page can omit the image element entirely rather than
    request one and handle the 404. A console full of failed requests is a
    poor way to say "this scene was not cached".
    """
    return (CACHE_DIR / "thumbs" / f"{region_code}_{observed_on}.png").is_file()


def _row_to_dict(row: OpticalIndexObservation, region: Region) -> dict:
    """One stored reading, with the caveats it needs to be read correctly."""
    characterises = row.water_pixels >= MIN_WATER_PIXELS
    observed_on = row.observed_on.isoformat()
    return {
        "has_thumbnail": _has_thumbnail(region.code, observed_on),
        "chlorophyll_cross_check": _chlorophyll_for(region.code),
        "region_code": region.code,
        "region_name": region.name,
        "observed_on": observed_on,
        "ndci_mean": round(row.ndci_mean, 4),
        "ndci_p50": round(row.ndci_p50, 4),
        "ndti_mean": round(row.ndti_mean, 4),
        "ndti_p50": round(row.ndti_p50, 4),
        "fdi_mean": round(row.fdi_mean, 5),
        "fdi_p90": round(row.fdi_p90, 5),
        "fdi_label": FDI_LABEL,
        "water_pixels": row.water_pixels,
        "total_pixels": row.total_pixels,
        "water_fraction": (
            round(row.water_pixels / row.total_pixels, 4) if row.total_pixels else 0.0
        ),
        "max_cloud_pct": row.max_cloud_pct,
        "evidence_level": row.evidence_level,
        "source": row.source,
        "attribution": COPERNICUS_ATTRIBUTION.format(year=row.observed_on.year),
        "characterises_region": characterises,
        "caveat": (
            None
            if characterises
            else (
                f"Computed from {row.water_pixels} water pixel"
                f"{'' if row.water_pixels == 1 else 's'} of "
                f"{row.total_pixels:,} sampled: the cell was almost entirely "
                "land or cloud on this pass. Too little sea was observed for "
                "these values to describe the region."
            )
        ),
    }


@router.get("/optical-indices", summary="Real Sentinel-2 indices by region")
def list_indices(
    latest_only: bool = Query(
        True, description="One row per region, its most recent acquisition."
    ),
    region: str | None = Query(None, description="Restrict to one region code."),
    limit: int = Query(400, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    """Stored Sentinel-2 indices, newest first.

    ``latest_only`` gives the table the overview page shows: the most recent
    acquisition per region. Without it, the full history is returned, which
    is what a per-region chart needs.
    """
    regions = {r.id: r for r in db.scalars(select(Region)).all()}

    statement = select(OpticalIndexObservation)
    if region:
        matched = next((r for r in regions.values() if r.code == region), None)
        if matched is None:
            raise HTTPException(status_code=404, detail=f"No region {region!r}")
        statement = statement.where(OpticalIndexObservation.region_id == matched.id)

    rows = list(
        db.scalars(
            statement.order_by(
                OpticalIndexObservation.observed_on.desc(),
                OpticalIndexObservation.region_id,
            ).limit(limit)
        ).all()
    )

    if latest_only:
        seen: set[int] = set()
        newest = []
        for row in rows:  # already ordered newest first
            if row.region_id in seen:
                continue
            seen.add(row.region_id)
            newest.append(row)
        rows = newest

    items = [
        _row_to_dict(row, regions[row.region_id])
        for row in rows
        if row.region_id in regions
    ]
    items.sort(key=lambda d: d["region_name"])

    total = db.scalar(select(func.count(OpticalIndexObservation.id))) or 0
    cells_with_data = (
        db.scalar(
            select(func.count(func.distinct(OpticalIndexObservation.region_id)))
        )
        or 0
    )
    newest_date = db.scalar(select(func.max(OpticalIndexObservation.observed_on)))

    return {
        "items": items,
        "provenance": {
            "evidence_level": "OBSERVED",
            "is_real": True,
            "source": "Copernicus Sentinel-2 L2A via Sentinel Hub Statistics API",
            "attribution": COPERNICUS_ATTRIBUTION.format(
                year=newest_date.year if newest_date else 2026
            ),
            "contains_simulated_data": False,
            "note": (
                "Measured values from Sentinel-2 acquisitions on the dates "
                "shown. Only pixels the scene classification layer marks as "
                "water are included, so a coastal cell reports on its sea. "
                "Regions with no row had no acquisition in the window that "
                "cleared the cloud limit; nothing is substituted for them."
            ),
        },
        "totals": {
            "readings_stored": total,
            "regions_with_data": cells_with_data,
            "regions_total": len(regions),
            "newest_acquisition": newest_date.isoformat() if newest_date else None,
            "min_water_pixels": MIN_WATER_PIXELS,
        },
        "indices": INDEX_NOTES,
    }


@router.get(
    "/optical-indices/{region_code}/thumbnail",
    summary="True-colour Sentinel-2 thumbnail",
)
def thumbnail(region_code: str, observed_on: str) -> FileResponse:
    """The cached scene a region's reading was computed from.

    Served from the fetch job's cache. A missing file is a 404 rather than a
    placeholder image: showing stock blue where a scene should be would make
    an absent observation look like a present one.
    """
    # The path is built from a resolved cache file, not from user input: the
    # candidate must be inside CACHE_DIR/thumbs or it is not served.
    candidate = (CACHE_DIR / "thumbs" / f"{region_code}_{observed_on}.png").resolve()
    root = (CACHE_DIR / "thumbs").resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No cached Sentinel-2 thumbnail for {region_code} on "
                f"{observed_on}."
            ),
        )
    return FileResponse(Path(candidate), media_type="image/png")


def _cached_currents() -> dict[str, dict]:
    """Every region's most recent cached CMEMS surface current.

    Read from the fetch job's cache rather than a table: currents are
    context for the map and the drift simulator, not something this platform
    claims to have measured.
    """
    from app.vision.cmems_client import (
        ATTRIBUTION as CMEMS_ATTRIBUTION,
    )
    from app.vision.cmems_client import (
        CACHE_DIR as CMEMS_CACHE,
    )
    from app.vision.cmems_client import CurrentReading

    out: dict[str, dict] = {}
    for path in sorted(CMEMS_CACHE.glob("current_*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            reading = CurrentReading(**payload)
        except Exception:  # noqa: BLE001
            continue
        if reading.cell_code in out:
            continue
        out[reading.cell_code] = {
            "speed_ms": round(reading.speed_ms, 4),
            "direction_deg": round(reading.direction_deg, 1),
            "valid_on": reading.valid_on,
            "evidence_level": "INFERRED",
            "attribution": CMEMS_ATTRIBUTION,
        }
    return out


@router.get("/marine-conditions", summary="Current wind, waves and SST by region")
def marine_conditions(db: Session = Depends(get_db)) -> dict:
    """Open-Meteo conditions for every monitored region, from the cache.

    Served from whatever the last fetch stored, with the time of that fetch
    attached. No live call: a weather service having a bad afternoon must not
    slow a page, and a demo must not depend on one.

    An empty cache is reported as empty. There is no synthetic weather.
    """
    cached = MarineConditionsClient.load()
    if not cached:
        return {
            "items": [],
            "fetched_at": None,
            "available": False,
            "detail": (
                "No marine conditions have been fetched. Run "
                "scripts/fetch_marine_conditions.py. Nothing is substituted."
            ),
            "provenance": {
                "provider": MARINE_PROVIDER,
                "attribution": MARINE_ATTRIBUTION,
                "evidence_level": MARINE_EVIDENCE_LEVEL,
            },
        }

    regions = {r.code: r for r in db.scalars(select(Region)).all()}
    names = {code: r.name for code, r in regions.items()}
    currents = _cached_currents()
    chlorophyll = {
        code: _chlorophyll_for(code) for code in regions
    }

    items = []
    for item in cached.get("items", []):
        code = item["cell_code"]
        enriched = dict(item)
        enriched["region_name"] = names.get(code, code)
        # Currents and chlorophyll ride along so the map can draw them
        # without a second round trip per layer.
        enriched["surface_current"] = currents.get(code)
        enriched["chlorophyll"] = chlorophyll.get(code)
        region = regions.get(code)
        if region is not None:
            enriched["bbox"] = [
                region.min_lon,
                region.min_lat,
                region.max_lon,
                region.max_lat,
            ]
        items.append(enriched)
    items.sort(key=lambda d: d["region_name"])

    with_wind = [i for i in items if i.get("wind_speed_ms") is not None]
    ambiguous = [i for i in items if i.get("sar_ambiguous")]

    return {
        "items": items,
        "fetched_at": cached.get("fetched_at"),
        "available": bool(with_wind),
        "detail": cached.get("error"),
        "totals": {
            "regions": len(items),
            "with_wind": len(with_wind),
            "low_wind_regions": len(ambiguous),
            "low_wind_threshold_ms": LOW_WIND_MS,
        },
        "provenance": {
            "provider": MARINE_PROVIDER,
            "attribution": MARINE_ATTRIBUTION,
            "evidence_level": MARINE_EVIDENCE_LEVEL,
            "contains_simulated_data": False,
            "note": (
                "Numerical weather prediction output from Open-Meteo, not a "
                "satellite observation: an analysis of conditions constrained "
                "by measurements but produced by a model, hence INFERRED. "
                "Below "
                f"{LOW_WIND_MS} m/s a flat sea surface looks like oil in SAR, "
                "so dark formations in those regions are ambiguous."
            ),
        },
    }


@router.get("/vessel-activity", summary="Real vessel activity by region (GFW)")
def vessel_activity(db: Session = Depends(get_db)) -> dict:
    """Aggregate AIS-derived vessel activity per region, from the cache.

    Aggregate on purpose. This platform does not attach a real vessel
    identity to any detection -- its candidates are research benchmark
    patches and demonstration events, and naming a real ship as the source of
    one would be an accusation about something that never happened. "How busy
    is this water" is the question GFW can answer here honestly, and it is
    useful context for a dark formation without implicating anybody.
    """
    names = {r.code: r.name for r in db.scalars(select(Region)).all()}

    # One row per region, newest window. The cache key includes the window,
    # so a region fetched over two date ranges has two files, and summing or
    # listing both would double-count its traffic.
    newest: dict[str, RegionActivity] = {}
    for path in sorted(GFW_CACHE_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            activity = RegionActivity(**payload)
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        # Regions only. Ad-hoc boxes used for probing are not places.
        if activity.cell_code not in names:
            continue
        held = newest.get(activity.cell_code)
        if held is None or activity.window_to > held.window_to:
            newest[activity.cell_code] = activity

    items = []
    for activity in newest.values():
        row = activity.to_dict()
        row["region_name"] = names[activity.cell_code]
        items.append(row)

    items.sort(key=lambda d: -d["total_hours"])
    active = [i for i in items if i["total_hours"] > 0]

    return {
        "items": items,
        "available": bool(items),
        "totals": {
            "regions_answered": len(items),
            "regions_with_activity": len(active),
            "total_vessel_hours": round(sum(i["total_hours"] for i in items), 1),
            "total_vessels": sum(i["vessel_count"] for i in items),
        },
        "provenance": {
            "provider": GFW_PROVIDER,
            "attribution": GFW_ATTRIBUTION,
            "attribution_url": GFW_ATTRIBUTION_URL,
            "evidence_level": GFW_EVIDENCE_LEVEL,
            "product": GFW_PRODUCT,
            "contains_simulated_data": False,
            "note": (
                "Apparent fishing effort derived from AIS. 'Apparent' is "
                "GFW's own word: the activity is inferred from how a vessel "
                "moves, not reported by it, which is why this is INFERRED "
                "rather than OBSERVED. A region showing none observed means "
                "GFW answered and saw no effort there -- not that the "
                "question failed."
            ),
            "identity_note": (
                "No vessel identity is stored or shown. The vessels named "
                "elsewhere in this platform as detection suspects are "
                "fictional and labelled as such."
            ),
        },
    }


#: Where the incident replay writes its result and thumbnail.
REPLAY_DIR = CACHE_DIR.parent / "incident_replay"


@router.get("/incident-replay", summary="Historical incident replay results")
def incident_replay() -> dict:
    """Documented real incidents replayed through the SAR detector.

    Screening ordinary water and finding nothing is weak evidence, because a
    detector that always answered "no" would behave identically. These are
    incidents known to have happened, with a position and date from an
    official source, put through the same pipeline.

    Negative results are served exactly like positive ones. A finding that
    only appears when it is favourable is not a finding.
    """
    items = []
    for path in sorted(REPLAY_DIR.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return {
        "items": items,
        "available": bool(items),
        "note": (
            "A replay is validation evidence, not a monitoring product. A "
            "negative means the detector did not flag the site on the "
            "satellite passes that existed -- not that nothing was there."
        ),
    }


@router.get(
    "/incident-replay/{name}/thumbnail", summary="Replay scene thumbnail"
)
def replay_thumbnail(name: str) -> FileResponse:
    """The prepared SAR tile over the incident position."""
    candidate = (REPLAY_DIR / name).resolve()
    if REPLAY_DIR.resolve() not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"No replay thumbnail {name!r}")
    return FileResponse(Path(candidate), media_type="image/png")
