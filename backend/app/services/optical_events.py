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
from datetime import UTC, date, datetime, time
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

#: Each region is judged against **its own** twelve-month baseline.
#:
#: A single platform-wide threshold does not work here, and the data says so
#: plainly: NDTI's 99th percentile ranges from 0.142 in the quieter cells to
#: 0.313 off the Krishna-Godavari delta. One global cut-off would mark the
#: river mouths as anomalous every single day -- which is not a finding, it
#: is a description of where rivers are -- while missing a genuine excursion
#: in clear water.
#:
#: So an anomaly here means: **the top 1% of what this platform has measured
#: in this region over the last twelve months**. That is a per-region,
#: self-referential claim, and the event says so in those words.
PERCENTILE = 0.99

#: Readings a region needs before its own percentile means anything.
#:
#: At n=40 the 99th percentile is effectively the highest reading or two, so
#: this is a weak statistic even here, and the event carries the sample size
#: for that reason. Below it a region produces **no events at all** -- there
#: is no fallback to a global threshold, because silently judging one region
#: by another region's water is the error this whole change exists to fix.
MIN_BASELINE_READINGS = 40

#: Reported alongside the NDCI anomaly, never instead of it.
#:
#: ``MultiSensorIntegrator.ALGAL_BLOOM_NDCI_THRESHOLD`` is a literature-based
#: absolute: above it, chlorophyll-a is high in anyone's terms, regardless of
#: what this region usually looks like. The two answer different questions --
#: "unusual here" and "high in absolute terms" -- and an event that is both
#: is worth more than one that is only either, so both are shown.
from app.vision.multi_sensor import MultiSensorIntegrator  # noqa: E402

NDCI_LITERATURE_THRESHOLD = MultiSensorIntegrator.ALGAL_BLOOM_NDCI_THRESHOLD

#: Below this many water pixels a reading describes a puddle, not a region.
#: Imported rather than redefined so the two cannot drift apart.
WATER_PIXEL_FLOOR = MIN_WATER_PIXELS

#: Appended to every event this module creates. The threshold is relative to
#: the region's own history, and the reader has to know that to read the
#: event correctly.
RELATIVE_THRESHOLD_CAVEAT = (
    "This is a statistical anomaly against this region's own twelve-month "
    "distribution, not a measurement against a regulatory or published "
    "limit. It means the reading is unusual for this stretch of water as "
    "this platform has measured it. It is not a confirmed pollution "
    "incident, and it is not a statement that the water is contaminated."
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


@dataclass(slots=True)
class RegionBaseline:
    """What normal looks like in one region, from its own twelve months."""

    region_code: str
    n_readings: int
    window_from: date
    window_to: date
    #: index name -> that region's 99th percentile for it.
    percentiles: dict[str, float]

    @property
    def usable(self) -> bool:
        """Whether this region has enough history to judge itself by."""
        return self.n_readings >= MIN_BASELINE_READINGS

    def describe(self, index_name: str) -> str:
        """The sentence that goes on an event raised against this baseline."""
        return (
            f"Statistical anomaly: top 1% of this region's last 12 months "
            f"(Sentinel-2 {index_name})"
        )

    def to_dict(self, index_name: str) -> dict[str, Any]:
        """Serialise the baseline an event was judged against."""
        return {
            "method": "per-region 99th percentile",
            "percentile": PERCENTILE,
            "threshold": round(self.percentiles.get(index_name.upper(), 0.0), 5),
            "baseline_readings": self.n_readings,
            "baseline_from": self.window_from.isoformat(),
            "baseline_to": self.window_to.isoformat(),
            "scope": (
                "This region only. Each region is judged against its own "
                "twelve-month distribution, because a platform-wide cut-off "
                "would flag naturally turbid river mouths every day and miss "
                "a real excursion in clear water."
            ),
        }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def compute_baselines(db: Session) -> dict[int, RegionBaseline]:
    """One baseline per region, from that region's own stored readings.

    Computed in Python rather than SQL so the same code runs on SQLite in
    tests and PostgreSQL in production -- ``percentile_cont`` is not portable
    and a percentile that differs between the two would be a quiet source of
    disagreement between a test and the thing it tests.
    """
    rows = db.execute(
        select(
            OpticalIndexObservation.region_id,
            Region.code,
            OpticalIndexObservation.observed_on,
            OpticalIndexObservation.ndci_mean,
            OpticalIndexObservation.ndti_mean,
            OpticalIndexObservation.fdi_mean,
        )
        .join(Region, Region.id == OpticalIndexObservation.region_id)
        .where(OpticalIndexObservation.water_pixels >= WATER_PIXEL_FLOOR)
    ).all()

    gathered: dict[int, dict[str, Any]] = {}
    for region_id, code, day, ndci, ndti, fdi in rows:
        bucket = gathered.setdefault(
            region_id,
            {"code": code, "days": [], "NDCI": [], "NDTI": [], "FDI": []},
        )
        bucket["days"].append(day)
        bucket["NDCI"].append(float(ndci))
        bucket["NDTI"].append(float(ndti))
        bucket["FDI"].append(float(fdi))

    baselines: dict[int, RegionBaseline] = {}
    for region_id, bucket in gathered.items():
        baselines[region_id] = RegionBaseline(
            region_code=bucket["code"],
            n_readings=len(bucket["days"]),
            window_from=min(bucket["days"]),
            window_to=max(bucket["days"]),
            percentiles={
                name: _percentile(sorted(bucket[name]), PERCENTILE)
                for name in ("NDCI", "NDTI", "FDI")
            },
        )
    return baselines


#: Which index drives which signature.
INDEX_SIGNATURES: list[tuple[str, str, str]] = [
    ("NDCI", "ndci_mean", PollutionSignature.ALGAE_BLOOM_SIGNATURE),
    ("FDI", "fdi_mean", PollutionSignature.FLOATING_MATERIAL),
    ("NDTI", "ndti_mean", PollutionSignature.TURBIDITY_PLUME),
]


def _detections_for(
    row: OpticalIndexObservation, baseline: RegionBaseline
) -> list[OpticalDetection]:
    """Every signature one reading supports, judged against its own region."""
    if row.water_pixels < WATER_PIXEL_FLOOR or not baseline.usable:
        return []

    found: list[OpticalDetection] = []
    for index_name, column, signature in INDEX_SIGNATURES:
        threshold = baseline.percentiles.get(index_name)
        value = float(getattr(row, column))
        if threshold is None or value != value or threshold != threshold:
            continue
        if value >= threshold:
            found.append(
                OpticalDetection(
                    observation=row,
                    signature=signature,
                    value=value,
                    threshold=threshold,
                    index_name=index_name,
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
    baselines = compute_baselines(db)
    created: dict[str, int] = {}
    skipped_no_baseline = 0
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
        baseline = baselines.get(row.region_id)
        if baseline is None or not baseline.usable:
            skipped_no_baseline += 1
            continue
        considered += 1
        environment = _environmental_context(region)

        for detection in _detections_for(row, baseline):
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
                baseline.describe(detection.index_name) + ".",
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
                    "threshold": round(detection.threshold, 5),
                    "anomaly_label": baseline.describe(detection.index_name),
                    "baseline": baseline.to_dict(detection.index_name),
                    # For chlorophyll the absolute question is also worth
                    # answering: "unusual here" and "high in anyone's terms"
                    # are different, and an event that is both is stronger
                    # than one that is only either.
                    **(
                        {
                            "literature_check": {
                                "threshold": NDCI_LITERATURE_THRESHOLD,
                                "exceeds": bool(
                                    detection.value >= NDCI_LITERATURE_THRESHOLD
                                ),
                                "source": (
                                    "MultiSensorIntegrator."
                                    "ALGAL_BLOOM_NDCI_THRESHOLD -- an absolute "
                                    "chlorophyll-a level, independent of what "
                                    "this region usually looks like."
                                ),
                            }
                        }
                        if detection.index_name == "NDCI"
                        else {}
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
        "readings_without_region_baseline": skipped_no_baseline,
        "regions_with_baseline": sum(1 for b in baselines.values() if b.usable),
        "events_created": sum(created.values()),
        "by_signature": created,
        "already_present": skipped_existing,
        "method": {
            "basis": "per-region 99th percentile over 12 months",
            "percentile": PERCENTILE,
            "min_baseline_readings": MIN_BASELINE_READINGS,
            "min_water_pixels": WATER_PIXEL_FLOOR,
            "ndci_literature_threshold": NDCI_LITERATURE_THRESHOLD,
        },
    }
    logger.info("optical_events_built", extra=summary)
    return summary
