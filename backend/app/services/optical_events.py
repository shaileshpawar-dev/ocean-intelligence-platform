"""Turn real Sentinel-2 index readings into detections the platform can score.

Each stored :class:`OpticalIndexObservation` is a measured band ratio over one
region on one acquisition date. This module decides which of those readings
are anomalous enough to be worth raising as a :class:`PollutionEvent`, and
runs the existing deterministic risk engine over them.

Three signatures, one per index:

``algae_bloom_signature``  from NDCI, elevated chlorophyll-a
``floating_material``      from FDI, near-infrared brighter than the water
``turbidity_plume``        from NDTI, elevated suspended sediment

**Where the thresholds come from, and what they are not.** There is no
published absolute cut-off for any of these indices that holds across water
types: NDCI calibrations are regional, and Biermann's FDI work thresholds
against *local background* rather than a constant. So two of the three
thresholds here are **percentiles of this platform's own stored
distribution**, computed once from 253 readings over 35 Indian regions and
written down below with the figures they came from.

That makes a detection here a statement of the form *"this reading is
unusual for Indian coastal water as this platform has measured it"* — which
is a real, checkable claim, and is **not** the same as "this water is
polluted". The caveat travels on every event in ``caveats``, and the
signature names what was seen rather than what caused it.

Nothing is created from a reading that did not clear the water-pixel floor:
an index over eight pixels is arithmetic, not a measurement, and raising an
event from one would be the worst thing this module could do.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import PollutionEvent, Region, RiskAssessment
from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature
from app.models.optical import OpticalIndexObservation
from app.risk.engine import get_risk_engine
from app.vision.sentinel2_indices import FDI_LABEL, MIN_WATER_PIXELS

logger = get_logger(__name__)

#: Thresholds: the 99th percentile of this platform's own measured
#: distribution, over **2,744 readings across 36 Indian regions spanning
#: 21 Nov 2025 to 20 Nov 2026** (recomputed 21 Nov 2026).
#:
#: They were first set from a 30-day sample, and one of them was wrong
#: because of it. NDTI's 95th percentile over those 30 November days was
#: -0.0082 -- every reading negative -- while over the full year it is
#: +0.0281. The 30-day window was winter; the year includes the monsoon.
#: A threshold fitted to the quiet season flagged **14% of all readings** as
#: turbidity plumes, which is not an anomaly detector, it is a thermometer
#: reading the season.
#:
#: All three now sit at p99, so "flagged" means the same thing for each:
#: the top one percent of what this platform has measured in Indian coastal
#: water. That is a checkable claim and a deliberately weak one.

#: NDCI p99 = 0.1961. Kept at 0.20 because Mishra & Mishra (2012) put the
#: productive end of their chlorophyll-a calibration there too -- the
#: literature anchor and this dataset's own distribution agree, which is
#: worth more than either alone.
NDCI_BLOOM = 0.20

#: FDI p99 = 0.1028. Biermann et al. (2020) threshold against local
#: background rather than a constant, and no constant transfers between
#: water types, so this is explicitly "unusual for this coast as measured
#: here".
FDI_FLOATING = 0.10

#: NDTI p99 = 0.1011. See the note above about the seasonal error this
#: replaces.
NDTI_PLUME = 0.10

#: Below this many water pixels a reading describes a puddle, not a region.
#: Imported rather than redefined so the two cannot drift apart.
WATER_PIXEL_FLOOR = MIN_WATER_PIXELS

#: Appended to every event this module creates. The thresholds are relative,
#: and the reader has to know that to read the event correctly.
RELATIVE_THRESHOLD_CAVEAT = (
    "Flagged by comparison with this platform's own measured distribution "
    "over Indian coastal water, not against an absolute published limit. "
    "It means this reading is unusual for these waters as measured here. "
    "It is not a statement that the water is polluted."
)

SIGNATURE_CAVEATS: dict[str, list[str]] = {
    PollutionSignature.ALGAE_BLOOM_SIGNATURE: [
        "NDCI responds to chlorophyll-a. Elevated chlorophyll means "
        "productive water, which may be a bloom, a seasonal upwelling or a "
        "river nutrient plume. The index does not distinguish them.",
        "Not validated against an in-situ sample.",
    ],
    PollutionSignature.FLOATING_MATERIAL: [
        f"FDI responds to {FDI_LABEL} -- anything floating that is brighter "
        "in the near-infrared than the water around it. Biermann et al. "
        "(2020) cannot separate plastics from seaweed, foam, timber or "
        "spume without further spectral analysis, and sun glint raises the "
        "index too. This is not evidence of plastic.",
        "At 10 m resolution a positive pixel is roughly a tennis court of "
        "material, so small items are invisible and a positive is an "
        "aggregate.",
    ],
    PollutionSignature.TURBIDITY_PLUME: [
        "NDTI responds to suspended sediment. Much of the Indian coast is "
        "naturally turbid, and river discharge and post-monsoon runoff raise "
        "it without any pollutant being present.",
        "Turbidity is a water condition, not a pollutant.",
    ],
}


@dataclass(slots=True)
class OpticalDetection:
    """One index reading judged anomalous, before it becomes an event."""

    observation: OpticalIndexObservation
    signature: str
    #: The index value that triggered it, and the threshold it cleared.
    value: float
    threshold: float
    index_name: str

    @property
    def exceedance(self) -> float:
        """How far past the threshold, in index units."""
        return self.value - self.threshold

    @property
    def confidence(self) -> float:
        """An uncalibrated score in [0, 1], from how far past the threshold.

        Deliberately crude and deliberately capped. A band ratio one notch
        over a percentile is not 90% likely to be anything; this maps a
        clearly-exceeding reading to roughly 0.5-0.8 and says in the event's
        caveats that it is uncalibrated. It is a ranking aid, not a
        probability.
        """
        if self.threshold == 0:
            span = abs(self.value) or 1.0
        else:
            span = abs(self.threshold)
        ratio = self.exceedance / span if span else 0.0
        return round(min(0.85, 0.45 + max(0.0, ratio) * 0.5), 4)


def _detections_for(row: OpticalIndexObservation) -> list[OpticalDetection]:
    """Every signature one reading supports. Usually none."""
    if row.water_pixels < WATER_PIXEL_FLOOR:
        return []

    found: list[OpticalDetection] = []
    if row.ndci_mean >= NDCI_BLOOM:
        found.append(
            OpticalDetection(
                observation=row,
                signature=PollutionSignature.ALGAE_BLOOM_SIGNATURE,
                value=row.ndci_mean,
                threshold=NDCI_BLOOM,
                index_name="NDCI",
            )
        )
    if row.fdi_mean >= FDI_FLOATING:
        found.append(
            OpticalDetection(
                observation=row,
                signature=PollutionSignature.FLOATING_MATERIAL,
                value=row.fdi_mean,
                threshold=FDI_FLOATING,
                index_name="FDI",
            )
        )
    if row.ndti_mean >= NDTI_PLUME:
        found.append(
            OpticalDetection(
                observation=row,
                signature=PollutionSignature.TURBIDITY_PLUME,
                value=row.ndti_mean,
                threshold=NDTI_PLUME,
                index_name="NDTI",
            )
        )
    return found


def optical_event_id(region_code: str, observed_on: Any, signature: str) -> str:
    """Stable id for one (region, date, signature).

    Deterministic so re-running over the same readings recognises the events
    it already stored instead of multiplying them.
    """
    digest = hashlib.sha256(
        f"s2|{region_code}|{observed_on}|{signature}".encode()
    ).hexdigest()
    return f"evt_s2_{digest[:14]}"


def _area_km2(row: OpticalIndexObservation) -> float:
    """Water actually observed in the cell, in square kilometres.

    The sampling grid is 1 km per pixel by construction (see
    ``sentinel2_indices.TARGET_METRES_PER_PIXEL``), so the water pixel count
    *is* the observed area. This is the extent the index was averaged over --
    **not** the extent of the anomaly, which a regional mean cannot give. The
    event says so in its ``area_method``.
    """
    return float(row.water_pixels)


def _environmental_context(region: Region) -> dict[str, Any]:
    """Real sea state and current for the region, from the caches.

    Attached to the event rather than folded into the risk score. The risk
    engine's six factors and their weights are fixed and tested; quietly
    adding wind as a seventh would renormalise every score in the database
    and make today's numbers incomparable with yesterday's. So this is
    context a reader and the agent layer can use, carrying its own
    provenance, and the score stays the score.
    """
    context: dict[str, Any] = {}

    from app.vision.marine_conditions import (
        ATTRIBUTION as METEO_ATTRIBUTION,
    )
    from app.vision.marine_conditions import (
        LOW_WIND_MS,
        MarineConditionsClient,
    )

    cached = MarineConditionsClient.load() or {}
    for item in cached.get("items", []):
        if item.get("cell_code") != region.code:
            continue
        context["sea_state"] = {
            "wind_speed_ms": item.get("wind_speed_ms"),
            "wind_gust_ms": item.get("wind_gust_ms"),
            "wave_height_m": item.get("wave_height_m"),
            "sea_surface_temp_c": item.get("sea_surface_temp_c"),
            "observed_at": item.get("observed_at"),
            "low_wind_threshold_ms": LOW_WIND_MS,
            "evidence_level": "INFERRED",
            "attribution": METEO_ATTRIBUTION,
        }
        break

    import json as _json

    from app.vision.cmems_client import (
        ATTRIBUTION as CMEMS_ATTRIBUTION,
    )
    from app.vision.cmems_client import CACHE_DIR as CMEMS_CACHE, CurrentReading

    for path in sorted(CMEMS_CACHE.glob(f"current_{region.code}_*.json"), reverse=True):
        try:
            reading = CurrentReading(**_json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
        context["surface_current"] = {
            "speed_ms": round(reading.speed_ms, 4),
            "direction_deg": round(reading.direction_deg, 1),
            "valid_on": reading.valid_on,
            "evidence_level": "INFERRED",
            "attribution": CMEMS_ATTRIBUTION,
            "note": "Bearing the water flows toward (oceanographic convention).",
        }
        break

    return context


def build_optical_events(
    db: Session, *, commit: bool = True
) -> dict[str, Any]:
    """Create pollution events from stored Sentinel-2 index readings.

    Idempotent: an event already present for a (region, date, signature) is
    left alone. Returns a summary of what was created.
    """
    regions = {r.id: r for r in db.scalars(select(Region)).all()}
    rows = list(
        db.scalars(
            select(OpticalIndexObservation).order_by(
                OpticalIndexObservation.observed_on.desc()
            )
        ).all()
    )

    engine = get_risk_engine()
    created: dict[str, int] = {}
    skipped_existing = 0
    skipped_low_water = 0
    considered = 0

    for row in rows:
        region = regions.get(row.region_id)
        if region is None:
            continue
        if row.water_pixels < WATER_PIXEL_FLOOR:
            skipped_low_water += 1
            continue
        considered += 1
        environment = _environmental_context(region)

        for detection in _detections_for(row):
            event_id = optical_event_id(
                region.code, row.observed_on, detection.signature
            )
            if db.scalar(
                select(PollutionEvent.id).where(PollutionEvent.event_id == event_id)
            ):
                skipped_existing += 1
                continue

            area = _area_km2(row)
            risk = engine.assess(
                signature=str(detection.signature),
                confidence=detection.confidence,
                latitude=region.centroid_lat,
                longitude=region.centroid_lon,
                estimated_area_km2=area,
                evidence_level=EvidenceLevel.INFERRED,
            )

            caveats = [
                RELATIVE_THRESHOLD_CAVEAT,
                *SIGNATURE_CAVEATS.get(detection.signature, []),
                "Detector confidence is uncalibrated: it encodes how far the "
                "reading sits past the threshold, not a probability.",
            ]

            event = PollutionEvent(
                event_id=event_id,
                region_id=region.id,
                observation_id=None,
                signature=str(detection.signature),
                detection_method=str(DetectionMethod.OPTICAL_INDEX),
                evidence_level=str(EvidenceLevel.DETECTED),
                confidence=detection.confidence,
                latitude=region.centroid_lat,
                longitude=region.centroid_lon,
                bbox=[
                    region.min_lon,
                    region.min_lat,
                    region.max_lon,
                    region.max_lat,
                ],
                estimated_area_km2=area,
                # varchar(64): the short label here, the explanation in
                # `extra["area_basis"]` and in the caveats.
                area_method="water_pixels_observed_1km_grid",
                risk_score=risk.score,
                severity=str(risk.severity),
                detected_at=datetime.combine(
                    row.observed_on, time(0, 0), tzinfo=UTC
                ),
                model_version=f"optical-index:{detection.index_name.lower()}-1.0",
                caveats=caveats,
                extra={
                    "index": detection.index_name,
                    "index_value": round(detection.value, 5),
                    "threshold": detection.threshold,
                    "threshold_basis": (
                        "literature (Mishra & Mishra 2012)"
                        if detection.index_name == "NDCI"
                        else "95th percentile of this platform's stored readings"
                    ),
                    "area_basis": (
                        "Water pixels observed in the cell at 1 km sampling. "
                        "This is the area the index was averaged over, not "
                        "the extent of the anomaly, which a regional mean "
                        "cannot establish."
                    ),
                    "water_pixels": row.water_pixels,
                    "total_pixels": row.total_pixels,
                    "max_cloud_pct": row.max_cloud_pct,
                    "source": row.source,
                    "acquired_on": row.observed_on.isoformat(),
                    "attribution": (
                        f"Contains modified Copernicus Sentinel data "
                        f"{row.observed_on.year}"
                    ),
                    "is_real": True,
                    **(
                        {"environment": environment}
                        if environment
                        else {
                            "environment_note": (
                                "No cached sea state or current for this "
                                "region. Absent rather than assumed."
                            )
                        }
                    ),
                },
            )
            db.add(event)
            db.flush()

            db.add(
                RiskAssessment(
                    assessment_id=f"risk_s2_{event_id[-10:]}",
                    event_id=event.id,
                    score=risk.score,
                    severity=str(risk.severity),
                    engine_version=risk.engine_version,
                    contributions=[c.to_dict() for c in risk.contributions],
                    missing_factors=risk.missing_factors,
                    evidence_level=str(risk.evidence_level),
                    narrative=risk.narrative,
                )
            )
            created[str(detection.signature)] = (
                created.get(str(detection.signature), 0) + 1
            )

    if commit:
        db.commit()

    summary = {
        "readings_total": len(rows),
        "readings_considered": considered,
        "readings_below_water_floor": skipped_low_water,
        "events_created": sum(created.values()),
        "by_signature": created,
        "already_present": skipped_existing,
        "thresholds": {
            "ndci_bloom": NDCI_BLOOM,
            "fdi_floating": FDI_FLOATING,
            "ndti_plume": NDTI_PLUME,
            "min_water_pixels": WATER_PIXEL_FLOOR,
        },
    }
    logger.info("optical_events_built", extra=summary)
    return summary
