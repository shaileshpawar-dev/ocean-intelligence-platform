"""SAR candidate review dashboard and analyst decision API routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import make_provenance
from app.core.database import get_db
from app.schemas.candidate import (
    CandidateMapPointOut,
    CandidateReviewCreateIn,
    OpticalSceneOut,
    ProcessOpticalEvidenceIn,
    SARCandidateDetailOut,
    SARCandidateOpticalEvidenceOut,
    SARCandidateOut,
    SARCandidateReviewOut,
    SARCandidateSummaryOut,
    MultiSensorAssessmentOut,
)
from app.schemas.common import ListResponse
from app.schemas.vessel import CandidateVesselAssociationOut
from app.schemas.drift import DriftSimulationOut, DriftSimulationRequestIn
from app.schemas.environmental_impact import CandidateImpactAssessmentOut
from app.services import environmental_impact_service
from app.services import drift_service
from app.services import vessel_service
from app.services import candidate_service

router = APIRouter(prefix="/sar-candidates", tags=["sar-candidates"])

def _format_optical_record(e: Any, candidate_id: str) -> dict[str, Any]:
    return {
        "id": e.id,
        "candidate_id": candidate_id,
        "scene_id": e.scene_id,
        "platform": e.platform,
        "acquisition_timestamp": e.acquisition_timestamp,
        "temporal_offset_hours": e.temporal_offset_hours,
        "temporal_window": e.temporal_window,
        "scene_cloud_cover_pct": e.scene_cloud_cover_pct,
        "tile_id": e.tile_id,
        "local_water_fraction": e.local_water_fraction,
        "local_cloud_fraction": e.local_cloud_fraction,
        "local_shadow_fraction": e.local_shadow_fraction,
        "local_valid_pixel_fraction": e.local_valid_pixel_fraction,
        "mean_ndci": e.mean_ndci,
        "p90_ndci": e.p90_ndci,
        "mean_ndti": e.mean_ndti,
        "mean_swir_ratio": e.mean_swir_ratio,
        "optical_quality_flag": e.optical_quality_flag,
        "has_rgb_image": bool(e.rgb_thumbnail_path and Path(e.rgb_thumbnail_path).exists()),
        "has_false_color_image": bool(e.false_color_path and Path(e.false_color_path).exists()),
        "has_scl_mask": bool(e.scl_mask_path and Path(e.scl_mask_path).exists()),
        "has_ndci_map": bool(e.ndci_map_path and Path(e.ndci_map_path).exists()),
        "processing_status": e.processing_status,
        "created_at": e.created_at,
    }



@router.get(
    "",
    response_model=ListResponse[SARCandidateOut],
    summary="List experimental SAR oil-slick candidates",
)
def list_sar_candidates(
    screening_status: str | None = Query(
        None,
        description="Filter by screening state: 'candidate_requires_review', 'low_wind_ambiguity_review', 'no_candidate_detected'",
    ),
    review_status: str | None = Query(
        None,
        description="Filter by review state: 'awaiting_review', 'potential_oil_slick', 'rejected_lookalike', 'inconclusive', 'requires_additional_evidence'",
    ),
    model_version: str | None = Query(None, description="e.g. '2.2.0-experimental'"),
    is_coastal: bool | None = Query(None, description="Filter for coastal or offshore patches"),
    search: str | None = Query(None, description="Search candidate ID or patch image"),
    start_date: datetime | None = Query(None, description="Earliest acquisition time"),
    end_date: datetime | None = Query(None, description="Latest acquisition time"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ListResponse[SARCandidateOut]:
    """Retrieve filtered experimental SAR oil-slick candidates."""
    # Ensure database is seeded
    candidate_service.seed_candidates_from_audit(db)

    items, total = candidate_service.list_candidates(
        db=db,
        screening_status=screening_status,
        review_status=review_status,
        model_version=model_version,
        is_coastal=is_coastal,
        search=search,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    out_items = [SARCandidateOut.model_validate(it) for it in items]
    return ListResponse[SARCandidateOut](
        count=total,
        items=out_items,
        provenance=make_provenance(
            "sar_candidates:v2.2_era5",
            [{"evidence_level": "DETECTED", "is_simulated": False}],
            notes=["Experimental candidate screening layer. Preserves raw model confidence."],
        ),
    )


@router.get(
    "/summary",
    response_model=SARCandidateSummaryOut,
    summary="Summary metrics for candidate review dashboard",
)
def get_candidate_summary(
    db: Session = Depends(get_db),
) -> SARCandidateSummaryOut:
    """Return summary KPI statistics for standard and low-wind review queues."""
    summary_data = candidate_service.get_candidate_summary(db)
    return SARCandidateSummaryOut(**summary_data)


@router.get(
    "/map-points",
    response_model=list[CandidateMapPointOut],
    summary="Map layer points with visually distinct screening and review states",
)
def get_candidate_map_points(
    db: Session = Depends(get_db),
) -> list[CandidateMapPointOut]:
    """Retrieve lightweight Geo points for the Ocean Map candidate review layer."""
    points = candidate_service.get_map_points(db)
    return [CandidateMapPointOut(**p) for p in points]


@router.get(
    "/{candidate_id}",
    response_model=SARCandidateDetailOut,
    summary="Candidate detail with physical interpretation and review history",
)
def get_sar_candidate_detail(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> SARCandidateDetailOut:
    """Retrieve full SAR candidate details, ERA5 environmental context, and audit history."""
    candidate_service.seed_candidates_from_audit(db)
    cand = candidate_service.get_candidate(db, candidate_id)
    if cand is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id!r} not found.",
        )

    interpretation = candidate_service.generate_interpretation(cand)
    reviews_out = [SARCandidateReviewOut.model_validate(r) for r in cand.reviews]

    cand_dict = SARCandidateOut.model_validate(cand).model_dump()
    cand_dict["interpretation"] = interpretation
    cand_dict["reviews"] = reviews_out
    cand_dict["optical_evidence"] = [
        _format_optical_record(e, cand.candidate_id) for e in cand.optical_evidence
    ]
    return SARCandidateDetailOut(**cand_dict)


@router.post(
    "/{candidate_id}/reviews",
    response_model=SARCandidateDetailOut,
    summary="Submit an analyst review decision on a SAR candidate",
)
def review_sar_candidate(
    candidate_id: str,
    payload: CandidateReviewCreateIn,
    db: Session = Depends(get_db),
) -> SARCandidateDetailOut:
    """Record an auditable review decision.

    Preserves previous state, decision, reviewer ID, timestamp, model version, and notes.
    Operates in local-development review mode without fabricating authentication.
    """
    try:
        cand, _ = candidate_service.create_review(
            db=db,
            candidate_id=candidate_id,
            decision=payload.decision,
            reviewer_id=payload.reviewer_id,
            notes=payload.notes,
            evidence_references=payload.evidence_references,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    interpretation = candidate_service.generate_interpretation(cand)
    reviews_out = [SARCandidateReviewOut.model_validate(r) for r in cand.reviews]
    cand_dict = SARCandidateOut.model_validate(cand).model_dump()
    cand_dict["interpretation"] = interpretation
    cand_dict["reviews"] = reviews_out
    cand_dict["optical_evidence"] = [
        _format_optical_record(e, cand.candidate_id) for e in cand.optical_evidence
    ]
    return SARCandidateDetailOut(**cand_dict)


@router.get(
    "/{candidate_id}/image",
    summary="Retrieve local Sentinel-1 SAR JPEG patch image preview",
)
def get_sar_candidate_image(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """Serve the real Sentinel-1 SAR JPEG patch file using neutral filename headers."""
    cand = candidate_service.get_candidate(db, candidate_id)
    if cand is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id!r} not found.",
        )
    img_path = candidate_service.get_candidate_image_path(db, candidate_id)
    if img_path is None or not img_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image preview for candidate {candidate_id!r} not found.",
        )
    neutral_name = cand.neutral_image_id or f"{cand.candidate_id}.jpg"
    return FileResponse(img_path, media_type="image/jpeg", filename=neutral_name)

# -- Sentinel-2 Optical Evidence Endpoints (Phase 14.1) -----------------------

@router.get(
    "/{candidate_id}/optical-scenes",
    response_model=list[OpticalSceneOut],
    summary="Discover matching Sentinel-2 Level-2A scenes from CDSE STAC",
)
def get_candidate_optical_scenes(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> list[OpticalSceneOut]:
    """Query Copernicus Data Space STAC for intersecting Sentinel-2 Level-2A granules."""
    try:
        scenes = candidate_service.discover_optical_scenes(db, candidate_id)
        return [OpticalSceneOut(**s) for s in scenes]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Discovery failed: {e}")


@router.get(
    "/{candidate_id}/optical-evidence",
    response_model=list[SARCandidateOpticalEvidenceOut],
    summary="Retrieve processed optical evidence records for a candidate",
)
def list_candidate_optical_evidence(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> list[SARCandidateOpticalEvidenceOut]:
    """Get all persisted optical evidence records for this SAR candidate."""
    try:
        records = candidate_service.get_candidate_optical_evidence(db, candidate_id)
        return [_format_optical_record(r, candidate_id) for r in records]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/{candidate_id}/optical-evidence/process",
    response_model=SARCandidateOpticalEvidenceOut,
    summary="Extract windowed optical chips and generate optical evidence",
)
def process_candidate_optical_evidence(
    candidate_id: str,
    payload: ProcessOpticalEvidenceIn = ProcessOpticalEvidenceIn(),
    db: Session = Depends(get_db),
) -> SARCandidateOpticalEvidenceOut:
    """Extract windowed multi-spectral rasters, compute SCL/NDCI, render visualizations, and persist."""
    try:
        evidence = candidate_service.process_candidate_optical_evidence(
            db=db,
            candidate_id=candidate_id,
            scene_id=payload.scene_id,
            chip_size=payload.chip_size,
        )
        return _format_optical_record(evidence, candidate_id)
    except candidate_service.NoOpticalSceneError as e:
        # 404, not 500: Copernicus has no scene here, which is a fact about
        # satellite coverage rather than a failure of this service. The
        # panel renders the message instead of a chip.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Processing failed: {e}")


@router.get(
    "/{candidate_id}/optical-evidence/{evidence_id}/image/{product_type}",
    summary="Serve rendered optical evidence product image (PNG)",
)
def get_candidate_optical_image(
    candidate_id: str,
    evidence_id: int,
    product_type: str,
    db: Session = Depends(get_db),
) -> Response:
    """Serve rendered truecolour, falsecolour, scl, or ndci PNG image."""
    img_path = candidate_service.get_candidate_optical_image_path(
        db=db,
        candidate_id=candidate_id,
        evidence_id=evidence_id,
        product_type=product_type,
    )
    if img_path is None or not img_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optical product {product_type!r} for candidate {candidate_id!r} not found.",
        )
    return FileResponse(img_path, media_type="image/png", filename=f"{candidate_id}_{product_type}.png")



@router.get(
    "/{candidate_id}/fusion",
    response_model=MultiSensorAssessmentOut,
    summary="Retrieve multi-sensor evidence fusion and concordance assessment",
)
def get_candidate_fusion(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> MultiSensorAssessmentOut:
    """Triangulate SAR damping texture, ERA5 wind context, and Sentinel-2 optical indices."""
    assessment = candidate_service.get_candidate_fusion_assessment(db, candidate_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id!r} not found.",
        )
    return MultiSensorAssessmentOut(**assessment)


@router.get(
    "/{candidate_id}/vessels",
    response_model=list[CandidateVesselAssociationOut],
    summary="Retrieve correlated proximate AIS vessels for a candidate",
)
def get_candidate_vessels(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> list[CandidateVesselAssociationOut]:
    """Return correlated vessels within the spatio-temporal search window.

    **The vessels named here are fictional.** They are seeded synthetic
    tracks, not live or historical AIS, and the association score is a
    proximity heuristic -- it does not identify who was responsible for
    anything.

    This is deliberate and it is not a gap waiting to be filled with real
    data. The candidates in this platform are research benchmark patches and
    demonstration events; no oil was spilled by anyone. Putting a real MMSI
    into a ``SOURCE_SUSPECT`` row at a confidence of 0.97 would name an
    identifiable ship as the source of a spill that never happened.

    Real vessel data does appear in this platform, at
    ``/api/v1/vessel-activity``: aggregate AIS-derived activity per region
    from Global Fishing Watch, with no identities attached to any
    detection.
    """
    return vessel_service.get_candidate_vessel_associations(db, candidate_id)


@router.post(
    "/{candidate_id}/vessels/correlate",
    response_model=list[CandidateVesselAssociationOut],
    summary="Trigger spatio-temporal AIS trajectory correlation",
)
def correlate_candidate_vessels(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> list[CandidateVesselAssociationOut]:
    """Re-correlate vessel tracks against a candidate's coordinates and time.

    Operates on the same fictional seeded tracks as ``GET
    /{candidate_id}/vessels``; see that endpoint for why no real vessel
    identity is used here.
    """
    try:
        return vessel_service.trigger_candidate_vessel_correlation(db, candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/{candidate_id}/drift",
    response_model=DriftSimulationOut,
    summary="Retrieve or auto-run Lagrangian oil drift simulation for a candidate",
)
def get_candidate_drift(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> DriftSimulationOut:
    """Simulate 48-hour forward drift trajectory and weathering mass balance."""
    return drift_service.get_candidate_drift_simulation(db, candidate_id)


@router.post(
    "/{candidate_id}/drift",
    response_model=DriftSimulationOut,
    summary="Execute custom Lagrangian oil drift simulation for a candidate",
)
def run_candidate_drift(
    candidate_id: str,
    payload: DriftSimulationRequestIn,
    db: Session = Depends(get_db),
) -> DriftSimulationOut:
    """Execute custom duration/volume drift simulation using candidate coordinates and wind."""
    payload.candidate_id = candidate_id
    return drift_service.run_drift_simulation(db, payload)


@router.get(
    "/{candidate_id}/impact",
    response_model=CandidateImpactAssessmentOut,
    summary="Retrieve environmental vulnerability assessment for sensitive marine receptors",
)
def get_candidate_impact(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> CandidateImpactAssessmentOut:
    """Evaluate spatial exposure to Marine Protected Areas, coral reefs, and coastal intakes."""
    return environmental_impact_service.get_candidate_environmental_impact(db, candidate_id)


@router.post(
    "/{candidate_id}/impact/evaluate",
    response_model=CandidateImpactAssessmentOut,
    summary="Re-evaluate environmental impact against marine receptors",
)
def evaluate_candidate_impact(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> CandidateImpactAssessmentOut:
    """Force spatial proximity and vulnerability index re-calculation."""
    return environmental_impact_service.evaluate_candidate_environmental_impact(db, candidate_id)


@router.get(
    "/{candidate_id}/vessel-activity",
    summary="Aggregate vessel activity near a candidate (Global Fishing Watch)",
)
def candidate_vessel_activity(
    candidate_id: str, db: Session = Depends(get_db)
) -> dict:
    """How busy this water was around the candidate's acquisition.

    **Aggregate only, and deliberately so.** Hours and vessel counts by flag
    state, from Global Fishing Watch. No name, no MMSI, no "suspect", no
    source attribution of any kind.

    These candidates are research benchmark patches: the detections were
    never established as real releases, so naming a ship against one would
    be an accusation about an event that did not happen. "How busy was this
    water" is the question the data can answer honestly, and it is useful
    to a reviewer without implicating anybody.

    A zero is a finding: GFW answered and saw no apparent effort there.
    """
    from datetime import UTC

    from app.vision.gfw_client import (
        ATTRIBUTION,
        ATTRIBUTION_URL,
        CANDIDATE_RADIUS_KM,
        CANDIDATE_WINDOW_DAYS,
        EVIDENCE_LEVEL,
        candidate_activity,
        get_gfw_client,
    )

    candidate = candidate_service.get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candidate {candidate_id!r}",
        )

    moment = candidate.acquisition_timestamp
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    activity = candidate_activity(
        get_gfw_client(),
        candidate_id,
        candidate.latitude,
        candidate.longitude,
        moment,
    )

    base = {
        "candidate_id": candidate_id,
        "label": "Vessel activity nearby",
        "radius_km": CANDIDATE_RADIUS_KM,
        "window_days": CANDIDATE_WINDOW_DAYS,
        "acquisition": moment.isoformat(),
        "evidence_level": EVIDENCE_LEVEL,
        "attribution": ATTRIBUTION,
        "attribution_url": ATTRIBUTION_URL,
        "identity_note": (
            "Aggregate only. No vessel is named, and nothing here attributes "
            "a detection to a ship: these are benchmark patches, not "
            "established releases."
        ),
    }

    if activity is None:
        return {
            **base,
            "available": False,
            "detail": (
                "Global Fishing Watch could not be reached for this window. "
                "Nothing is substituted."
            ),
        }

    return {
        **base,
        "available": True,
        "total_hours": round(activity.total_hours, 1),
        "vessel_count": activity.vessel_count,
        "grid_cells": activity.grid_cells,
        "window_from": activity.window_from,
        "window_to": activity.window_to,
        "top_flags": [
            {"flag": flag, "hours": round(hours, 1)}
            for flag, hours in activity.top_flags
        ],
        "detail": (
            "No apparent fishing effort recorded in this window."
            if activity.total_hours == 0
            else (
                f"{activity.vessel_count} vessel(s) over "
                f"{activity.total_hours:.0f} hours within "
                f"{CANDIDATE_RADIUS_KM:.0f} km."
            )
        ),
    }
