"""Satellite ingestion, imagery and image-upload detection endpoints."""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import demo_mode_notes
from app.core.database import get_db
from app.core.logging import get_logger, get_request_id
from app.gee import get_satellite_provider
from app.models import PredictionLog, Region
from app.schemas.pollution import DetectResponse, IngestionSummaryOut
from app.services.ingestion_service import run_ingestion
from app.services.refinement_service import DEFAULT_MAX_CELLS, refine_flagged_cells
from app.vision.registry import get_image_detector

logger = get_logger(__name__)
router = APIRouter(tags=["satellite"])

#: Guard against oversized uploads exhausting disk in a container.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


@router.post(
    "/satellite/ingest",
    response_model=IngestionSummaryOut,
    summary="Run one satellite ingestion cycle",
)
def ingest(
    lookback_days: int | None = Query(None, ge=1, le=60),
    db: Session = Depends(get_db),
) -> IngestionSummaryOut:
    """Fetch observations, run the SAR detector, score risk and persist.

    Synchronous by design at this scale (a few hundred cells). Move to a task
    queue once ingestion exceeds request-timeout budgets.
    """
    summary = run_ingestion(db, lookback_days=lookback_days)
    return IngestionSummaryOut(**summary.to_dict())


@router.post(
    "/satellite/refine",
    summary="Stage-2: subdivide flagged cells and re-observe at finer scale",
)
def refine(
    max_cells: int = Query(
        DEFAULT_MAX_CELLS, ge=1, le=20, description="Flagged cells to refine."
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Take a closer look at the cells the coarse sweep flagged.

    The screening grid is far too coarse to support a slick-scale claim, so
    stage 1 never emits more than ``dark_formation``. This endpoint
    subdivides the most anomalous cells and re-queries at finer scale, where
    a localised dark patch can reach a plausible slick extent and an
    ``oil_like_signature`` becomes defensible.

    Cost is bounded: only already-anomalous cells are refined, and at most
    ``max_cells`` of them per call.
    """
    summary = refine_flagged_cells(db, max_cells=max_cells)
    payload = summary.to_dict()
    payload["notes"] = demo_mode_notes()
    return payload


@router.get(
    "/satellite/thumbnail/{region_code}",
    summary="Satellite preview image for a region cell",
)
def thumbnail(
    region_code: str,
    dimensions: int = Query(512, ge=64, le=2048),
    db: Session = Depends(get_db),
) -> dict:
    """Return a rendered SAR preview URL, or an explicit null with a reason.

    Never fabricates an image. In demo mode there is no imagery, and the
    response says so rather than returning a placeholder that could be
    mistaken for a real acquisition.
    """
    region = db.scalar(select(Region).where(Region.code == region_code))
    if region is None:
        raise HTTPException(status_code=404, detail=f"No region {region_code!r}")

    provider = get_satellite_provider()
    bbox = [region.min_lon, region.min_lat, region.max_lon, region.max_lat]
    url = provider.get_thumbnail_url(bbox, dimensions=dimensions)

    return {
        "region_code": region_code,
        "region_name": region.name,
        "bbox": bbox,
        "url": url,
        "source": provider.name,
        "available": url is not None,
        "detail": (
            None
            if url
            else (
                "No imagery available from the active provider. Configure "
                "Earth Engine credentials to enable SAR previews."
            )
        ),
    }


@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Run the image detector on an uploaded image",
)
async def detect(
    file: UploadFile = File(...),
    min_lon: float | None = Query(None, description="Image west bound (WGS84)"),
    min_lat: float | None = Query(None, description="Image south bound (WGS84)"),
    max_lon: float | None = Query(None, description="Image east bound (WGS84)"),
    max_lat: float | None = Query(None, description="Image north bound (WGS84)"),
    db: Session = Depends(get_db),
) -> DetectResponse:
    """Detect pollution signatures in an uploaded image.

    Supply all four bounds to geolocate the detections. Without them the
    results carry pixel coordinates only and say so in their caveats -- the
    previous implementation assigned random world coordinates instead, which
    put detections in the wrong ocean.
    """
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type {suffix!r}. Allowed: {sorted(ALLOWED_SUFFIXES)}"
            ),
        )

    bounds = [min_lon, min_lat, max_lon, max_lat]
    geo_bounds = bounds if all(b is not None for b in bounds) else None

    detector = get_image_detector()
    request_id = get_request_id() or uuid.uuid4().hex[:16]

    tmp_dir = Path(tempfile.mkdtemp(prefix="oip_detect_"))
    tmp_path = tmp_dir / f"upload{suffix}"
    written = 0
    try:
        with tmp_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                    )
                out.write(chunk)

        started = time.perf_counter()
        try:
            detections = detector.predict(tmp_path, geo_bounds=geo_bounds)
        except RuntimeError as exc:
            _log_prediction(
                db,
                request_id=request_id,
                detector_name=detector.name,
                version=detector.version,
                latency_ms=(time.perf_counter() - started) * 1000,
                detections=[],
                error=str(exc),
            )
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        latency_ms = (time.perf_counter() - started) * 1000
        _log_prediction(
            db,
            request_id=request_id,
            detector_name=detector.name,
            version=detector.version,
            latency_ms=latency_ms,
            detections=detections,
            error=None,
        )

        notes = list(demo_mode_notes())
        if geo_bounds is None:
            notes.append("No geographic bounds supplied; detections are not geolocated.")
        if detector.name == "mock-detector":
            notes.append(
                "SIMULATED: the mock detector is active. These are not real "
                "detections. Set DETECTOR_BACKEND=yolo and YOLO_MODEL_PATH."
            )

        return DetectResponse(
            request_id=request_id,
            detector=detector.name,
            model_version=detector.version,
            detection_count=len(detections),
            latency_ms=round(latency_ms, 2),
            detections=[
                {
                    "signature": str(d.signature),
                    "class_name": d.class_name,
                    "confidence": round(d.confidence, 4),
                    "confidence_is_calibrated": d.confidence_is_calibrated,
                    "method": str(d.method),
                    "model_version": d.model_version,
                    "evidence_level": str(d.evidence_level),
                    "bbox": d.bbox,
                    "geo_bbox": d.geo_bbox,
                    "latitude": d.latitude,
                    "longitude": d.longitude,
                    "area_pixels": d.area_pixels,
                    "caveats": d.caveats,
                }
                for d in detections
            ],
            notes=notes,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _log_prediction(
    db: Session,
    *,
    request_id: str,
    detector_name: str,
    version: str,
    latency_ms: float,
    detections: list,
    error: str | None,
) -> None:
    """Persist one inference record for latency stats and drift monitoring."""
    confidences = [d.confidence for d in detections]
    try:
        db.add(
            PredictionLog(
                request_id=request_id,
                created_at=datetime.now(UTC),
                model_name=detector_name,
                model_version=version,
                endpoint="POST /api/v1/detect",
                latency_ms=latency_ms,
                detection_count=len(detections),
                max_confidence=max(confidences) if confidences else None,
                mean_confidence=(
                    sum(confidences) / len(confidences) if confidences else None
                ),
                predicted_classes=[str(d.signature) for d in detections],
                success=error is None,
                error=error,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("prediction_log_failed", exc_info=True)
