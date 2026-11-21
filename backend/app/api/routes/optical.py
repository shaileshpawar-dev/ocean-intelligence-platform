"""Real Sentinel-2 water-quality indices, per monitored region.

Serves stored rows only. No endpoint here calls Copernicus: fetching is a
job (``scripts/fetch_sentinel2_indices.py``), so a page load cannot be made
slow by a satellite API, and the demo runs from the database.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Region
from app.models.optical import OpticalIndexObservation
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

    names = {r.code: r.name for r in db.scalars(select(Region)).all()}
    items = []
    for item in cached.get("items", []):
        enriched = dict(item)
        enriched["region_name"] = names.get(item["cell_code"], item["cell_code"])
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
