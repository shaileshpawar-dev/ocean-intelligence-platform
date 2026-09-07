"""Bootstrap and demo-data seeding.

Two distinct things live here and must not be confused:

* :func:`bootstrap` is **not** demo data. It seeds structural rows -- the
  monitoring regions and the model-registry entries -- which are real
  configuration and run in every environment.
* :func:`seed_demo_data` generates synthetic history for demonstration. Every
  row it writes is tagged ``SIMULATED`` and it refuses to run unless
  ``DEMO_MODE`` is enabled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import (
    EvidenceLevel,
    ModelStatus,
    ModelVersion,
    PollutionEvent,
    SatelliteObservation,
)
from app.services.ingestion_service import ensure_regions

logger = get_logger(__name__)


def bootstrap(db: Session) -> None:
    """Ensure regions and registry entries exist. Idempotent."""
    ensure_regions(db)
    _register_known_models(db)


def _register_known_models(db: Session) -> None:
    """Register the detectors this deployment ships with.

    Metrics are left null. They are populated only by an actual evaluation
    run (``ml/evaluation/evaluate_detector.py``), because a registry entry
    claiming mAP 0.87 with no evaluation behind it is exactly the kind of
    number that does not survive a technical interview.
    """
    known = [
        {
            "name": "yolo-pollution-detector",
            "version": "yolov8m-best",
            "task": "detection",
            "framework": "ultralytics-yolov8",
            "status": str(ModelStatus.PRODUCTION),
            "is_deployed": settings.detector_backend == "yolo",
            # Read directly from best.pt, not copied from the notebook --
            # whose CLASS_NAMES had class 3 as "marine_debris" when the
            # checkpoint actually emits "chemical_pollution".
            "class_names": [
                "oil_spill",
                "algae_bloom",
                "plastic_waste",
                "chemical_pollution",
            ],
            "dataset_version": "pollution.yaml",
            "hyperparameters": {
                "epochs": 100,
                "imgsz": 640,
                "batch": 16,
                "lr0": 0.001,
                "optimizer": "auto",
                "patience": 20,
                "seed": 42,
                "pretrained": True,
                "ultralytics_version": "8.4.41",
            },
            "notes": (
                "Carried over from the original project; metadata read from "
                "the checkpoint (ultralytics 8.4.41, trained 2026-04-22). "
                "Licence: AGPL-3.0 via Ultralytics -- network deployment "
                "obliges source release unless a commercial licence is held. "
                "Metrics are null until an evaluation run against a held-out "
                "set records them: python -m ml.evaluation.evaluate_detector"
            ),
        },
        {
            "name": "sar-dark-formation",
            "version": "1.0.0",
            "task": "detection",
            "framework": "rule-based",
            "status": str(ModelStatus.PRODUCTION),
            "is_deployed": True,
            "class_names": [
                "oil_like_signature",
                "dark_formation",
                "no_anomaly",
            ],
            "notes": (
                "Threshold and contrast analysis on Sentinel-1 VV backscatter. "
                "Stage-one dark-formation detection only. Not validated "
                "against a labelled spill dataset, so its confidence is an "
                "uncalibrated score."
            ),
        },
    ]

    # Descriptive fields are configuration and must track the code; measured
    # fields are evidence and must never be overwritten here. Without this
    # split, correcting the class list (class 3 was wrongly recorded as
    # "marine_debris") would leave stale values in an existing database --
    # and a careless "update everything" would silently wipe metrics that an
    # evaluation run had earned.
    descriptive_fields = {
        "task",
        "framework",
        "status",
        "is_deployed",
        "class_names",
        "dataset_version",
        "hyperparameters",
        "notes",
    }

    for spec in known:
        existing = db.scalar(
            select(ModelVersion).where(
                ModelVersion.name == spec["name"],
                ModelVersion.version == spec["version"],
            )
        )
        if existing is None:
            db.add(ModelVersion(**spec))
            continue
        for field, value in spec.items():
            if field in descriptive_fields:
                setattr(existing, field, value)
    db.commit()


def _clear_simulated(db: Session) -> None:
    """Delete every SIMULATED record, leaving real data untouched.

    Ordered to respect foreign keys: events (and their cascaded risk
    assessments) before the observations they reference.
    """
    from sqlalchemy import delete

    from app.models import RiskAssessment, ZoneHistory

    simulated_event_ids = list(
        db.scalars(
            select(PollutionEvent.id).where(
                PollutionEvent.evidence_level == str(EvidenceLevel.SIMULATED)
            )
        ).all()
    )
    if simulated_event_ids:
        db.execute(
            delete(RiskAssessment).where(RiskAssessment.event_id.in_(simulated_event_ids))
        )
        db.execute(
            delete(PollutionEvent).where(PollutionEvent.id.in_(simulated_event_ids))
        )
    db.execute(
        delete(SatelliteObservation).where(
            SatelliteObservation.evidence_level == str(EvidenceLevel.SIMULATED)
        )
    )
    db.execute(delete(ZoneHistory))
    db.commit()
    logger.info("simulated_records_cleared", extra={"events": len(simulated_event_ids)})


def seed_demo_data(db: Session, days: int = 45, force: bool = False) -> dict:
    """Generate synthetic observation history so the dashboard has depth.

    Runs the real ingestion pipeline once per simulated day against the demo
    satellite provider, so the resulting history exercises the genuine
    detector, risk engine and aggregation code paths rather than writing
    pre-cooked rows.

    Args:
        db: Active session.
        days: How many days of history to generate.
        force: Regenerate even when history already exists.

    Returns:
        A summary dict.

    Raises:
        RuntimeError: If ``DEMO_MODE`` is disabled. Synthetic data must never
            be written into a production database.
    """
    if not settings.demo_mode:
        raise RuntimeError(
            "seed_demo_data requires DEMO_MODE=true. Refusing to write "
            "simulated records into a non-demo database."
        )

    existing = db.scalar(select(func.count(SatelliteObservation.id))) or 0
    if existing and not force:
        return {
            "status": "skipped",
            "reason": (
                f"{existing} observations already stored; pass force=true to regenerate."
            ),
        }

    if force:
        # Clear only SIMULATED records. Real observations, if any were ever
        # ingested into this database, are never destroyed by a demo reseed.
        _clear_simulated(db)

    from app.gee import all_cells
    from app.gee.demo_provider import DemoSatelliteProvider
    from app.risk.engine import get_risk_engine
    from app.services.analytics_service import rebuild_history
    from app.services.ingestion_service import _persist_observation
    from app.vision.registry import get_sar_detector

    regions = ensure_regions(db)
    detector = get_sar_detector()
    risk_engine = get_risk_engine()
    cells = all_cells()

    now = datetime.now(UTC)
    observations = events = 0

    for day_offset in range(days, 0, -1):
        # A different seed per day produces a genuinely varying series
        # instead of one snapshot perturbed by noise.
        provider = DemoSatelliteProvider(seed=f"oip-demo-day-{day_offset}")
        day = now - timedelta(days=day_offset)

        for obs in provider.get_observations(cells, lookback_days=1):
            region = regions.get(obs.cell_code)
            if region is None:
                continue
            obs.acquired_at = day
            record = _persist_observation(db, obs, region)
            observations += 1

            for det in detector.predict(obs.to_detector_input()):
                if str(det.signature) == "no_anomaly":
                    continue
                risk = risk_engine.assess(
                    signature=str(det.signature),
                    confidence=det.confidence,
                    latitude=det.latitude,
                    longitude=det.longitude,
                    estimated_area_km2=det.estimated_area_km2,
                    evidence_level=EvidenceLevel.SIMULATED,
                )
                db.add(
                    PollutionEvent(
                        event_id=f"evt_demo_{obs.cell_code}_{day_offset}",
                        region_id=region.id,
                        observation_id=record.id,
                        signature=str(det.signature),
                        detection_method=str(det.method),
                        evidence_level=str(EvidenceLevel.SIMULATED),
                        confidence=det.confidence,
                        latitude=det.latitude or region.centroid_lat,
                        longitude=det.longitude or region.centroid_lon,
                        estimated_area_km2=det.estimated_area_km2,
                        area_method=det.area_method,
                        risk_score=risk.score,
                        severity=str(risk.severity),
                        detected_at=day,
                        model_version=f"{detector.name}:{detector.version}",
                        caveats=[
                            "SIMULATED EVENT generated by demo mode. Not a "
                            "real detection.",
                            *det.caveats,
                        ],
                        extra=det.extra,
                    )
                )
                events += 1
        db.commit()

    buckets = rebuild_history(db)
    summary = {
        "status": "seeded",
        "days": days,
        "observations": observations,
        "events": events,
        "history_buckets": buckets,
        "evidence_level": str(EvidenceLevel.SIMULATED),
        "warning": (
            "All seeded records are SIMULATED and are tagged as such in every "
            "API response."
        ),
    }
    logger.info("demo_data_seeded", extra=summary)
    return summary
