"""Service layer for SAR candidate retrieval, environmental context, and analyst reviews.

Connects Sentinel-1 SAR candidate detections, ERA5 atmospheric reanalysis, and
auditable human decision history.
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.sar_candidate import SARCandidate, SARCandidateReview, SARCandidateOpticalEvidence

logger = get_logger(__name__)

# Resolve data artefacts from the repository root, not the process working
# directory. The backend is normally launched from ``backend/``, while the
# datasets live at the repository root.
DATA_ROOT = REPO_ROOT / "data"
DATA_DIR = DATA_ROOT / "training" / "sar_oil_v2"
IMAGES_DIR = DATA_DIR / "images"
TAB_PATH = DATA_DIR / "pangaea_980773_annotations.tab"
CACHE_PATH = DATA_ROOT / "cache" / "era5_wind_cache.json"
AUDIT_CSV_PATH = DATA_ROOT / "models" / "sar" / "v2_2_scene_clean" / "phase13_1_per_sample_audit.csv"


def _resolve_data_path(path_str: str | None) -> Path | None:
    """Resolve a stored evidence path against the repository root."""
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path

VALID_REVIEW_DECISIONS = {
    "potential_oil_slick",
    "rejected_lookalike",
    "inconclusive",
    "requires_additional_evidence",
}


def _load_tab_metadata() -> dict[str, dict[str, Any]]:
    """Parse PANGAEA metadata tab file for ground-truth satellite coordinates and timestamps."""
    metadata: dict[str, dict[str, Any]] = {}
    if not TAB_PATH.exists():
        return metadata

    with open(TAB_PATH, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("/*") or line.startswith("Image set"):
                continue
            parts = line.split("\t")
            if len(parts) >= 16:
                img_name = parts[1].strip()
                start_time = parts[5].strip()
                sentinel_id = parts[7].strip()
                ul_lon = float(parts[10]) if parts[10] else None
                ul_lat = float(parts[11]) if parts[11] else None
                br_lon = float(parts[14]) if parts[14] else ul_lon
                br_lat = float(parts[15]) if parts[15] else ul_lat
                center_lat = (ul_lat + br_lat) / 2.0 if (ul_lat and br_lat) else (ul_lat or 33.0)
                center_lon = (ul_lon + br_lon) / 2.0 if (ul_lon and br_lon) else (ul_lon or 33.0)
                safes = [s.strip() for s in sentinel_id.split(";") if s.strip()]

                metadata[img_name] = {
                    "center_lat": round(center_lat, 5),
                    "center_lon": round(center_lon, 5),
                    "start_time": start_time,
                    "safe_scene": safes[0] if safes else "S1_IW_GRDH_UNKNOWN.SAFE",
                }
    return metadata


def seed_candidates_from_audit(db: Session, force: bool = False) -> int:
    """Seed sar_candidates table with verified real candidate samples from Phase 13.1 audit."""
    existing_count = db.scalar(select(func.count(SARCandidate.id))) or 0
    if existing_count > 0 and not force:
        logger.info("sar_candidates_already_seeded", extra={"count": existing_count})
        return existing_count

    if not AUDIT_CSV_PATH.exists():
        logger.warning("sar_audit_csv_missing", extra={"path": str(AUDIT_CSV_PATH)})
        return 0

    tab_meta = _load_tab_metadata()
    cache_data: dict[str, dict[str, Any]] = {}
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
        except Exception:
            cache_data = {}

    if force:
        db.query(SARCandidateReview).delete()
        db.query(SARCandidate).delete()
        db.commit()

    candidates: list[SARCandidate] = []
    with open(AUDIT_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            img = row["image"]
            t_meta = tab_meta.get(img, {})
            c_meta = cache_data.get(img, {})

            # Assign neutral IDs for analyst-facing blindness while preserving internal provenance
            cid_slug = img.replace(".jpg", "").replace("-", "_")
            internal_sample_id = f"cand_{cid_slug}"
            neutral_candidate_id = f"cand_s1_{idx:04d}"
            neutral_img_id = f"patch_s1_{idx:04d}.jpg"

            # Parse acquisition timestamp
            raw_time = t_meta.get("start_time") or c_meta.get("acquisition_timestamp_utc") or "2019-01-01T00:00:00"
            clean_time = raw_time.rstrip("Z")
            try:
                acq_dt = datetime.fromisoformat(clean_time).replace(tzinfo=UTC)
            except Exception:
                acq_dt = datetime(2019, 1, 1, 0, 0, tzinfo=UTC)

            # Coordinates
            lat = t_meta.get("center_lat") or c_meta.get("grid_latitude") or 33.0
            lon = t_meta.get("center_lon") or c_meta.get("grid_longitude") or 33.0

            # Safe scene
            safe = row.get("safe_scene") or t_meta.get("safe_scene") or "S1B_IW_GRDH_2019.SAFE"

            # Parse numbers
            try:
                comp_id = int(row.get("component_id") or 0)
            except Exception:
                comp_id = None

            raw_conf = float(row.get("v2_2_p_oil") or 0.5)
            w_spd = float(row["wind_speed_ms"]) if row.get("wind_speed_ms") else None
            w_dir = float(row["wind_direction_deg"]) if row.get("wind_direction_deg") else None

            # Warnings list
            w_class = row.get("wind_classification", "UNKNOWN")
            warnings: list[str] = []
            if w_class == "LOW_WIND":
                warnings.append(
                    f"Low wind speed ({w_spd:.2f} m/s < 3.0 m/s): Surface capillary damping is physically "
                    "ambiguous due to lack of wind stress (natural calm water, biogenic films, wind shadows). "
                    "Candidate is flagged for analyst review with high ambiguity."
                )
            elif w_class == "HIGH_WIND":
                warnings.append(
                    f"High wind speed ({w_spd:.2f} m/s > 12.0 m/s): Strong wind and wave breaking disperse "
                    "mineral oil. Candidate is retained for analyst review with dispersion warning."
                )
            elif w_class == "WITHIN_SCREENING_RANGE":
                warnings.append(
                    f"Optimal wind speed ({w_spd:.2f} m/s within [3.0, 12.0] m/s): Sea surface supports Bragg "
                    "capillary waves; radar damping contrast is diagnostic. Candidate requires review."
                )

            is_coastal = row.get("is_coastal", "False").lower() in ("true", "1", "t")
            if is_coastal:
                warnings.append(
                    "Coastal proximity notice: ERA5 grid resolution (~31 km) may not fully resolve "
                    "sub-grid coastal topography and local island wind shadows."
                )

            cand = SARCandidate(
                candidate_id=neutral_candidate_id,
                internal_sample_id=internal_sample_id,
                neutral_image_id=neutral_img_id,
                image_name=img,
                safe_scene=safe,
                subset=row.get("subset", "ow"),
                cluster=row.get("cluster", "oil"),
                component_id=comp_id,
                split=row.get("split", "benchmark"),
                latitude=float(lat),
                longitude=float(lon),
                is_coastal=is_coastal,
                acquisition_timestamp=acq_dt,
                detector_name="sar-oil-slick-v2.2",
                model_version="2.2.0-experimental",
                raw_confidence=raw_conf,
                confidence_is_calibrated=False,
                wind_speed_ms=w_spd,
                wind_direction_deg=w_dir,
                era5_source=c_meta.get("source", "ECMWF ERA5 Reanalysis Archive"),
                grid_latitude=c_meta.get("grid_latitude"),
                grid_longitude=c_meta.get("grid_longitude"),
                temporal_offset_minutes=c_meta.get("temporal_offset_minutes"),
                grid_distance_km=c_meta.get("grid_distance_km"),
                quality_status=c_meta.get("quality_status", "reanalysis_available"),
                environmental_warnings=warnings,
                screening_status=row.get("screening_status", "candidate_requires_review"),
                retained_for_analyst_review=row.get("retained_for_analyst_review", "True").lower() == "true",
                review_status="awaiting_review",
            )
            candidates.append(cand)

    db.add_all(candidates)
    db.commit()
    logger.info("seeded_sar_candidates", extra={"count": len(candidates)})
    return len(candidates)


def list_candidates(
    db: Session,
    screening_status: str | None = None,
    review_status: str | None = None,
    model_version: str | None = None,
    is_coastal: bool | None = None,
    search: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[SARCandidate], int]:
    """Retrieve filtered SAR candidates and total matching count."""
    query = select(SARCandidate)

    if screening_status:
        query = query.where(SARCandidate.screening_status == screening_status)
    if review_status:
        query = query.where(SARCandidate.review_status == review_status)
    if model_version:
        query = query.where(SARCandidate.model_version == model_version)
    if is_coastal is not None:
        query = query.where(SARCandidate.is_coastal == is_coastal)
    if start_date:
        query = query.where(SARCandidate.acquisition_timestamp >= start_date)
    if end_date:
        query = query.where(SARCandidate.acquisition_timestamp <= end_date)
    if search:
        s_term = f"%{search}%"
        query = query.where(
            (SARCandidate.candidate_id.ilike(s_term))
            | (SARCandidate.neutral_image_id.ilike(s_term))
        )

    # Count matching
    count_stmt = select(func.count()).select_from(query.subquery())
    total_count = db.scalar(count_stmt) or 0

    # Paginate, ordering newest and highest confidence first
    items_stmt = (
        query.order_by(
            desc(SARCandidate.acquisition_timestamp),
            desc(SARCandidate.raw_confidence),
        )
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(items_stmt).all())
    return items, total_count


def get_candidate_summary(db: Session) -> dict[str, Any]:
    """Calculate summary metrics for candidate review dashboard cards with reconciled semantics.

    Distinguishes:
    - Total monitored samples (all evaluated SAR patches)
    - Eligible candidates (detections with p_oil >= 0.50)
    - Standard review queue (wind >= 3.0 m/s)
    - Low-wind ambiguity queue (wind < 3.0 m/s)
    - Background non-detections (p_oil < 0.50)
    - Awaiting analyst review (eligible candidates pending a review decision)
    - Reviewed candidates (candidates with audit decisions)
    """
    # Ensure database is seeded
    seed_candidates_from_audit(db)

    total_monitored = db.scalar(select(func.count(SARCandidate.id))) or 0

    # 1. Standard wind review: diagnostic wind (3.0 to 12.0 m/s) with detected candidate
    standard_wind_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                SARCandidate.screening_status == "candidate_requires_review",
                SARCandidate.wind_speed_ms.isnot(None),
                SARCandidate.wind_speed_ms >= 3.0,
                SARCandidate.wind_speed_ms <= 12.0,
            )
        )
        or 0
    )

    # 2. Low wind ambiguity: wind < 3.0 m/s
    low_wind_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                (SARCandidate.screening_status == "low_wind_ambiguity_review")
                | (
                    (SARCandidate.raw_confidence >= 0.50)
                    & (SARCandidate.wind_speed_ms.isnot(None))
                    & (SARCandidate.wind_speed_ms < 3.0)
                )
            )
        )
        or 0
    )

    # 3. High wind ambiguity: eligible candidate with ERA5 wind speed > 12.0 m/s
    high_wind_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                (
                    SARCandidate.screening_status.in_(
                        ["high_wind_ambiguity_review", "candidate_flagged_high_wind"]
                    )
                )
                | (
                    (SARCandidate.raw_confidence >= 0.50)
                    & (SARCandidate.wind_speed_ms.isnot(None))
                    & (SARCandidate.wind_speed_ms > 12.0)
                )
            )
        )
        or 0
    )

    # 4. Wind unavailable: eligible candidate with missing or unverified ERA5 reanalysis
    wind_unavail_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                SARCandidate.screening_status == "candidate_requires_review",
                SARCandidate.wind_speed_ms.is_(None),
            )
        )
        or 0
    )

    # 5. Background non-detections (p_oil < 0.50)
    no_cand_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                SARCandidate.screening_status == "no_candidate_detected"
            )
        )
        or 0
    )

    eligible_candidates = standard_wind_cnt + low_wind_cnt + high_wind_cnt + wind_unavail_cnt

    # Awaiting review counts ONLY eligible candidates (not background non-detections)
    awaiting_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                SARCandidate.raw_confidence >= 0.50,
                SARCandidate.review_status == "awaiting_review",
            )
        )
        or 0
    )
    reviewed_cnt = (
        db.scalar(
            select(func.count(SARCandidate.id)).where(
                SARCandidate.raw_confidence >= 0.50,
                SARCandidate.review_status != "awaiting_review",
            )
        )
        or 0
    )

    # Decision breakdowns
    decisions: dict[str, int] = {}
    for dec in VALID_REVIEW_DECISIONS:
        cnt = (
            db.scalar(
                select(func.count(SARCandidate.id)).where(
                    SARCandidate.review_status == dec
                )
            )
            or 0
        )
        decisions[dec] = cnt

    return {
        "total_candidates": total_monitored,
        "total_monitored_samples": total_monitored,
        "total_evaluated_samples": total_monitored,
        "eligible_candidates": eligible_candidates,
        "standard_review_candidates": standard_wind_cnt,
        "standard_wind_review": standard_wind_cnt,
        "low_wind_ambiguity_candidates": low_wind_cnt,
        "low_wind_ambiguity": low_wind_cnt,
        "high_wind_ambiguity_candidates": high_wind_cnt,
        "high_wind_ambiguity": high_wind_cnt,
        "wind_unavailable_candidates": wind_unavail_cnt,
        "wind_unavailable": wind_unavail_cnt,
        "no_candidate_detected": no_cand_cnt,
        "background_non_detections": no_cand_cnt,
        "awaiting_analyst_review": awaiting_cnt,
        "reviewed_candidates": reviewed_cnt,
        "decisions": decisions,
    }


def get_candidate(
    db: Session, candidate_id: str, allow_internal: bool = False
) -> SARCandidate | None:
    """Retrieve candidate with reviews by neutral candidate_id.

    Public analyst routes only query candidate_id to prevent ground-truth leakage.
    allow_internal is strictly reserved for internal research provenance audits.
    """
    if allow_internal:
        return db.scalar(
            select(SARCandidate).where(
                (SARCandidate.candidate_id == candidate_id)
                | (SARCandidate.internal_sample_id == candidate_id)
            )
        )
    return db.scalar(
        select(SARCandidate).where(SARCandidate.candidate_id == candidate_id)
    )


def generate_interpretation(candidate: SARCandidate) -> str:
    """Generate clear, scientifically honest physical explanation of screening status."""
    conf_pct = candidate.raw_confidence * 100.0
    w_spd = candidate.wind_speed_ms

    if candidate.screening_status == "no_candidate_detected":
        return (
            f"The experimental multi-scale CNN (SAR V2.2) did not detect an anomalous oil-like signature "
            f"(p_oil = {candidate.raw_confidence:.4f} < 0.50). Backscatter is consistent with unpolluted sea."
        )

    if candidate.screening_status == "low_wind_ambiguity_review":
        w_text = f"{w_spd:.2f} m/s" if w_spd is not None else "unspecified"
        return (
            f"The SAR V2.2 model identified a dark backscatter depression with an uncalibrated model score of {conf_pct:.1f}%. "
            f"However, collocated ECMWF ERA5 numerical reanalysis reports a 10m wind speed of {w_text} (< 3.0 m/s). "
            f"Physical Principle: In low-wind conditions, the absence of wind stress suppresses surface Bragg "
            f"capillary waves across clean water, causing natural calm cells, biogenic surfactant films, and "
            f"wind shadows to mimic petroleum damping. The candidate remains visible in the review queue with "
            f"high physical ambiguity flagged for secondary optical or in-situ verification."
        )

    w_text = f"{w_spd:.2f} m/s" if w_spd is not None else "unavailable"
    coastal_text = (
        " Note: Patch is located in a coastal zone; ERA5 reanalysis (~31 km grid) may not fully resolve "
        "local land-breeze or island wind-shadow effects."
        if candidate.is_coastal
        else ""
    )
    return (
        f"The SAR V2.2 model identified a candidate oil-slick signature with an uncalibrated model score of {conf_pct:.1f}%. "
        f"Collocated ERA5 numerical reanalysis indicates a 10m wind speed of {w_text}, which lies within the "
        f"favorable Bragg wave scattering regime (3.0 - 12.0 m/s). Petroleum damping contrast is physically "
        f"diagnostic under these sea-surface conditions.{coastal_text} Candidate is designated for standard review."
    )


def create_candidate_review(
    db: Session,
    candidate_id: str,
    decision: str,
    reviewer_id: str = "analyst_local",
    notes: str | None = None,
    evidence_references: dict[str, Any] | None = None,
) -> tuple[SARCandidate, SARCandidateReview]:
    """Record an auditable review decision on a SAR candidate."""
    if decision not in VALID_REVIEW_DECISIONS:
        raise ValueError(
            f"Invalid review decision {decision!r}. Must be one of: {sorted(VALID_REVIEW_DECISIONS)}"
        )

    cand = get_candidate(db, candidate_id)
    if cand is None:
        raise ValueError(f"Candidate {candidate_id!r} not found.")

    previous_status = cand.review_status
    now = utcnow()
    review_uuid = f"rev_{uuid.uuid4().hex[:12]}"

    # Update candidate state
    cand.review_status = decision
    cand.latest_review_decision = decision
    cand.latest_reviewed_at = now
    cand.latest_reviewer_id = reviewer_id
    cand.updated_at = now

    # Create application-enforced append-only audit row
    review = SARCandidateReview(
        review_id=review_uuid,
        candidate_id=cand.id,
        previous_status=previous_status,
        decision=decision,
        reviewer_id=reviewer_id,
        reviewed_at=now,
        model_version=cand.model_version,
        notes=notes,
        evidence_references=evidence_references or {},
        created_at=now,
    )
    db.add(review)
    db.commit()
    db.refresh(cand)
    db.refresh(review)

    logger.info(
        "sar_candidate_reviewed",
        extra={
            "candidate_id": candidate_id,
            "decision": decision,
            "reviewer_id": reviewer_id,
            "previous_status": previous_status,
        },
    )
    return cand, review


create_review = create_candidate_review


def get_candidate_image_path(db: Session, candidate_id: str) -> Path | None:
    """Resolve the local JPEG patch image path for preview."""
    cand = get_candidate(db, candidate_id)
    if cand is None:
        return None

    img_path = IMAGES_DIR / cand.image_name
    if img_path.exists():
        return img_path
    return None


def get_map_points(db: Session) -> list[dict[str, Any]]:
    """Retrieve all candidates formatted as lightweight map points with visually distinct states."""
    seed_candidates_from_audit(db)
    stmt = select(SARCandidate)
    candidates = list(db.scalars(stmt).all())

    points: list[dict[str, Any]] = []
    for c in candidates:
        # Determine map state
        if c.review_status == "potential_oil_slick":
            map_state = "reviewed_potential_oil"
            color = "#f97316"  # Orange
        elif c.review_status == "rejected_lookalike":
            map_state = "reviewed_rejected"
            color = "#64748b"  # Slate
        elif c.review_status == "inconclusive":
            map_state = "reviewed_inconclusive"
            color = "#3b82f6"  # Blue
        elif c.review_status == "requires_additional_evidence":
            map_state = "reviewed_requires_evidence"
            color = "#8b5cf6"  # Violet
        elif c.screening_status == "low_wind_ambiguity_review":
            map_state = "low_wind_ambiguity"
            color = "#ec4899"  # Pink / Magenta
        else:
            map_state = "standard_candidate"
            color = "#06b6d4"  # Cyan

        points.append({
            "candidate_id": c.candidate_id,
            "image_name": c.neutral_image_id or c.image_name,
            "latitude": c.latitude,
            "longitude": c.longitude,
            "screening_status": c.screening_status,
            "review_status": c.review_status,
            "raw_confidence": c.raw_confidence,
            "wind_speed_ms": c.wind_speed_ms,
            "is_coastal": c.is_coastal,
            "acquisition_timestamp": c.acquisition_timestamp.isoformat(),
            "map_state": map_state,
            "color": color,
        })
    return points

# -- Sentinel-2 Optical Evidence Services (Phase 14.1) ------------------------

def discover_optical_scenes(db: Session, candidate_id: str) -> list[dict[str, Any]]:
    """Query Copernicus Data Space STAC for Sentinel-2 scenes matching this candidate."""
    cand = get_candidate(db, candidate_id)
    if cand is None:
        raise ValueError(f"Candidate {candidate_id!r} not found.")

    from app.vision.copernicus_client import CopernicusSTACClient
    stac_client = CopernicusSTACClient()
    scenes = stac_client.get_candidate_optical_scenes(
        lat=cand.latitude,
        lon=cand.longitude,
        sar_timestamp=cand.acquisition_timestamp,
        primary_window_days=3.0,
        secondary_window_days=10.0,
    )
    return scenes


def get_candidate_optical_evidence(db: Session, candidate_id: str) -> list[SARCandidateOpticalEvidence]:
    """Retrieve persisted optical evidence records for a candidate."""
    cand = get_candidate(db, candidate_id)
    if cand is None:
        raise ValueError(f"Candidate {candidate_id!r} not found.")

    from app.models.sar_candidate import SARCandidateOpticalEvidence
    stmt = (
        select(SARCandidateOpticalEvidence)
        .where(SARCandidateOpticalEvidence.candidate_id == cand.id)
        .order_by(desc(SARCandidateOpticalEvidence.acquisition_timestamp))
    )
    return list(db.scalars(stmt).all())


class NoOpticalSceneError(Exception):
    """No usable Sentinel-2 scene exists for a candidate.

    A distinct exception so the API can answer with an explanation rather
    than a generic failure. The absence is a real finding about satellite
    coverage, not a fault in this platform, and the panel says so instead
    of rendering anything.
    """


def process_candidate_optical_evidence(
    db: Session,
    candidate_id: str,
    scene_id: str | None = None,
    chip_size: int = 512,
) -> SARCandidateOpticalEvidence:
    """Extract windowed optical chips, evaluate quality, render products, and persist evidence."""
    cand = get_candidate(db, candidate_id)
    if cand is None:
        raise ValueError(f"Candidate {candidate_id!r} not found.")

    from app.vision.copernicus_client import CopernicusSTACClient
    from app.vision.cog_extractor import COGExtractor
    from app.models.sar_candidate import SARCandidateOpticalEvidence

    stac_client = CopernicusSTACClient()
    scenes = stac_client.get_candidate_optical_scenes(
        lat=cand.latitude,
        lon=cand.longitude,
        sar_timestamp=cand.acquisition_timestamp,
    )

    if not scenes:
        raise NoOpticalSceneError(
            "No cloud-free Sentinel-2 scene within ±5 days of this "
            "candidate's acquisition."
        )

    # Pick specified scene or best match
    target_scene = None
    if scene_id:
        for s in scenes:
            if s["scene_id"] == scene_id:
                target_scene = s
                break
        if target_scene is None:
            raise ValueError(f"Scene {scene_id!r} not found in discoverable scenes for candidate {candidate_id}.")
    else:
        target_scene = scenes[0]  # sorted with best match first

    extractor = COGExtractor(chip_size=chip_size)
    try:
        result = extractor.extract_and_process(
            candidate_id=cand.candidate_id,
            lat=cand.latitude,
            lon=cand.longitude,
            scene_info=target_scene,
        )
    except COGExtractor.NoUsableScene as exc:
        # The catalogue listed a scene but Copernicus could not deliver
        # usable pixels for this exact position. Reported as the absence it
        # is, never filled in -- an invented chip and a real one render
        # identically, which is the whole problem.
        raise NoOpticalSceneError(
            "No cloud-free Sentinel-2 scene within ±5 days of this "
            f"candidate's acquisition. ({exc})"
        ) from exc

    metrics = result["metrics"]
    s2_acq_dt = datetime.fromisoformat(target_scene["acquisition_time"].replace("Z", "+00:00"))

    # Check if an existing optical record for this candidate and scene already exists
    existing = db.scalars(
        select(SARCandidateOpticalEvidence).where(
            SARCandidateOpticalEvidence.candidate_id == cand.id,
            SARCandidateOpticalEvidence.scene_id == target_scene["scene_id"],
        )
    ).first()

    if existing:
        evidence = existing
        evidence.temporal_offset_hours = target_scene["temporal_delta_hours"]
        evidence.temporal_window = target_scene["temporal_window"]
        evidence.scene_cloud_cover_pct = target_scene["cloud_cover_pct"]
        evidence.tile_id = target_scene["tile_id"]
        evidence.local_water_fraction = metrics.water_fraction
        evidence.local_cloud_fraction = metrics.cloud_fraction
        evidence.local_shadow_fraction = metrics.shadow_fraction
        evidence.local_valid_pixel_fraction = metrics.valid_pixel_fraction
        evidence.mean_ndci = metrics.mean_ndci
        evidence.p90_ndci = metrics.p90_ndci
        evidence.mean_ndti = metrics.mean_ndti
        evidence.mean_swir_ratio = metrics.mean_swir_ratio
        evidence.optical_quality_flag = metrics.optical_quality_flag
        evidence.rgb_thumbnail_path = result["rgb_thumbnail_path"]
        evidence.false_color_path = result["false_color_path"]
        evidence.scl_mask_path = result["scl_mask_path"]
        evidence.ndci_map_path = result["ndci_map_path"]
        evidence.summary_json = result["summary_json"]
        evidence.processing_status = "completed"
    else:
        evidence = SARCandidateOpticalEvidence(
            candidate_id=cand.id,
            scene_id=target_scene["scene_id"],
            platform=target_scene["platform"],
            acquisition_timestamp=s2_acq_dt,
            temporal_offset_hours=target_scene["temporal_delta_hours"],
            temporal_window=target_scene["temporal_window"],
            scene_cloud_cover_pct=target_scene["cloud_cover_pct"],
            tile_id=target_scene["tile_id"],
            local_water_fraction=metrics.water_fraction,
            local_cloud_fraction=metrics.cloud_fraction,
            local_shadow_fraction=metrics.shadow_fraction,
            local_valid_pixel_fraction=metrics.valid_pixel_fraction,
            mean_ndci=metrics.mean_ndci,
            p90_ndci=metrics.p90_ndci,
            mean_ndti=metrics.mean_ndti,
            mean_swir_ratio=metrics.mean_swir_ratio,
            optical_quality_flag=metrics.optical_quality_flag,
            rgb_thumbnail_path=result["rgb_thumbnail_path"],
            false_color_path=result["false_color_path"],
            scl_mask_path=result["scl_mask_path"],
            ndci_map_path=result["ndci_map_path"],
            summary_json=result["summary_json"],
            processing_status="completed",
        )
        db.add(evidence)

    db.commit()
    db.refresh(evidence)
    return evidence


def get_candidate_optical_image_path(
    db: Session,
    candidate_id: str,
    evidence_id: int,
    product_type: str,
) -> Path | None:
    """Retrieve filesystem path for rendered optical evidence product."""
    cand = get_candidate(db, candidate_id)
    if cand is None:
        return None

    from app.models.sar_candidate import SARCandidateOpticalEvidence
    evidence = db.get(SARCandidateOpticalEvidence, evidence_id)
    if evidence is None or evidence.candidate_id != cand.id:
        return None

    path_str = None
    if product_type in ("rgb", "truecolour"):
        path_str = evidence.rgb_thumbnail_path
    elif product_type in ("false_color", "falsecolour", "swir"):
        path_str = evidence.false_color_path
    elif product_type in ("scl", "scl_mask"):
        path_str = evidence.scl_mask_path
    elif product_type in ("ndci", "ndci_map"):
        path_str = evidence.ndci_map_path

    if path_str:
        p = _resolve_data_path(path_str)
        if p is not None and p.exists():
            return p
    return None



def get_candidate_fusion_assessment(
    db: Session,
    candidate_id: str,
) -> dict[str, Any] | None:
    """Compute and return multi-sensor physical evidence fusion assessment for a candidate."""
    cand = get_candidate(db, candidate_id)
    if cand is None:
        return None

    from app.vision.multi_sensor import MultiSensorIntegrator

    # Check if candidate has processed optical evidence
    opt_evidence_dict = None
    if cand.optical_evidence:
        best_opt = sorted(
            cand.optical_evidence,
            key=lambda e: (e.local_water_fraction, -abs(e.temporal_offset_hours)),
            reverse=True,
        )[0]
        opt_evidence_dict = {
            "scene_id": best_opt.scene_id,
            "acquisition_timestamp": best_opt.acquisition_timestamp.isoformat(),
            "temporal_offset_hours": best_opt.temporal_offset_hours,
            "cloud_coverage_fraction": best_opt.local_cloud_fraction,
            "valid_water_fraction": best_opt.local_water_fraction,
            "mean_ndci": best_opt.mean_ndci,
            "p90_ndci": best_opt.p90_ndci,
            "mean_ndti": best_opt.mean_ndti,
            "mean_swir_ratio": best_opt.mean_swir_ratio,
            "optical_quality_flag": best_opt.optical_quality_flag,
        }

    integrator = MultiSensorIntegrator()
    assessment = integrator.integrate(
        candidate_id=cand.candidate_id,
        latitude=cand.latitude,
        longitude=cand.longitude,
        sar_confidence=cand.raw_confidence,
        screening_status=cand.screening_status,
        model_version=cand.model_version,
        sar_time=cand.acquisition_timestamp,
        wind_speed_ms=cand.wind_speed_ms,
        wind_direction_deg=cand.wind_direction_deg,
        era5_temporal_offset_min=cand.temporal_offset_minutes,
        optical_evidence=opt_evidence_dict,
    )

    return assessment.to_dict()
