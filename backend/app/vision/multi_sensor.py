"""Multi-Sensor Marine Evidence Integration & Evidence Fusion Engine (Phase 14.3).

Triangulates marine surface anomalies across complementary satellite sensors,
atmospheric reanalysis, and optical multispectral indices:
1. Sentinel-1 C-band SAR: Surface capillary wave damping (Bragg scattering suppression).
2. ECMWF ERA5: 10m surface wind stress and direction for physical diagnostic plausibility.
3. Sentinel-2 MSI: BOA surface reflectance, NDCI chlorophyll differentiation, and SCL cloud masking.
4. Spatiotemporal cross-sensor co-registration and multi-sensor concordance scoring.

Scientific Foundation:
----------------------
- Brekke & Solberg (2005), "Oil spill detection by satellite remote sensing", Remote Sensing of Environment.
- Leifer et al. (2012), "State of the art satellite and airborne marine oil spill remote sensing", Marine Pollution Bulletin.
- Mishra & Mishra (2012), "Normalized difference chlorophyll index: A novel model for normalized chlorophyll-a".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.models.enums import PollutionSignature
from app.vision.wind_screener import ScreeningStatus, WindClassification


class ModalityType(str, Enum):
    SAR_C_BAND = "SAR_C_BAND"
    ERA5_ATMOSPHERIC_WIND = "ERA5_ATMOSPHERIC_WIND"
    OPTICAL_SENTINEL_2 = "OPTICAL_SENTINEL_2"
    AIS_VESSEL_TRAFFIC = "AIS_VESSEL_TRAFFIC"


class EvidenceConsistency(str, Enum):
    SUPPORTING = "supporting"
    CONFLICTING = "conflicting"
    INCONCLUSIVE = "inconclusive"
    UNAVAILABLE = "unavailable"


class ConcordanceLevel(str, Enum):
    MULTI_SENSOR_CONCORDANCE = "MULTI_SENSOR_CONCORDANCE"
    BIOGENIC_LOOKALIKE = "BIOGENIC_LOOKALIKE"
    CALM_WATER_AMBIGUITY = "CALM_WATER_AMBIGUITY"
    DISPERSED_HIGH_WIND = "DISPERSED_HIGH_WIND"
    SAR_WIND_SUPPORTED = "SAR_WIND_SUPPORTED_OPTICAL_PENDING"
    SAR_ONLY_UNCONFIRMED = "SAR_ONLY_UNCONFIRMED"
    NO_ANOMALY = "NO_ANOMALY"


@dataclass(slots=True)
class EvidenceItem:
    modality: ModalityType
    sensor: str
    acquisition_time_utc: str
    temporal_offset_hours: float | None
    signature: str
    confidence: float
    consistency: EvidenceConsistency
    description: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality.value,
            "sensor": self.sensor,
            "acquisition_time_utc": self.acquisition_time_utc,
            "temporal_offset_hours": self.temporal_offset_hours,
            "signature": self.signature,
            "confidence": round(self.confidence, 4),
            "consistency": self.consistency.value,
            "description": self.description,
            "metrics": self.metrics,
        }


@dataclass(slots=True)
class MultiSensorAssessment:
    candidate_id: str
    latitude: float
    longitude: float
    sar_screening_status: str
    wind_classification: str
    optical_verification_status: str
    concordance_score: float
    concordance_level: ConcordanceLevel
    triangulation_summary: str
    recommended_action: str
    evidence_items: list[EvidenceItem]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "sar_screening_status": self.sar_screening_status,
            "wind_classification": self.wind_classification,
            "optical_verification_status": self.optical_verification_status,
            "concordance_score": round(self.concordance_score, 3),
            "concordance_level": self.concordance_level.value,
            "triangulation_summary": self.triangulation_summary,
            "recommended_action": self.recommended_action,
            "evidence_items": [e.to_dict() for e in self.evidence_items],
            "generated_at": self.generated_at,
        }


class MultiSensorIntegrator:
    """Combines SAR screening with ERA5 wind reanalysis and Sentinel-2 optical multispectral evidence."""

    ALGAL_BLOOM_NDCI_THRESHOLD: float = 0.08  # NDCI > 0.08 indicates significant chlorophyll-a
    CLEAN_WATER_NDCI_MAX: float = 0.02

    def integrate(
        self,
        candidate_id: str,
        latitude: float,
        longitude: float,
        sar_confidence: float,
        screening_status: str,
        model_version: str,
        sar_time: datetime,
        wind_speed_ms: float | None = None,
        wind_direction_deg: float | None = None,
        era5_temporal_offset_min: float | None = None,
        optical_evidence: dict[str, Any] | None = None,
    ) -> MultiSensorAssessment:
        """Synthesize multi-sensor evidence into an objective physical concordance assessment."""
        evidence_list: list[EvidenceItem] = []

        # 1. Ingest Sentinel-1 SAR C-band Evidence
        sar_is_positive = sar_confidence >= 0.50
        sar_desc = (
            f"Sentinel-1 C-band SAR detects surface capillary wave damping (uncalibrated model score {sar_confidence * 100:.1f}%)."
            if sar_is_positive
            else f"Sentinel-1 SAR backscatter shows baseline ocean roughness without significant damping (uncalibrated model score {sar_confidence * 100:.1f}%)."
        )
        evidence_list.append(
            EvidenceItem(
                modality=ModalityType.SAR_C_BAND,
                sensor=f"Sentinel-1 C-SAR ({model_version})",
                acquisition_time_utc=sar_time.isoformat(),
                temporal_offset_hours=0.0,
                signature="dark_formation" if sar_is_positive else "no_anomaly",
                confidence=sar_confidence,
                consistency=EvidenceConsistency.SUPPORTING if sar_is_positive else EvidenceConsistency.INCONCLUSIVE,
                description=sar_desc,
                metrics={
                    "model_version": model_version,
                    "confidence_p_oil": round(sar_confidence, 4),
                    "damping_detected": sar_is_positive,
                },
            )
        )

        # 2. Ingest ECMWF ERA5 Wind Context
        w_offset_h = round(era5_temporal_offset_min / 60.0, 2) if era5_temporal_offset_min is not None else None
        if wind_speed_ms is not None:
            if 3.0 <= wind_speed_ms <= 12.0:
                wind_class = "WITHIN_SCREENING_RANGE"
                wind_consistency = EvidenceConsistency.SUPPORTING
                wind_desc = (
                    f"ERA5 10m wind speed ({wind_speed_ms:.2f} m/s) is within the optimal diagnostic range "
                    "(3.0 - 12.0 m/s), sustaining Bragg resonance and permitting surface slick visibility."
                )
            elif wind_speed_ms < 3.0:
                wind_class = "LOW_WIND"
                wind_consistency = EvidenceConsistency.CONFLICTING
                wind_desc = (
                    f"ERA5 10m wind speed ({wind_speed_ms:.2f} m/s) is below the 3.0 m/s diagnostic threshold. "
                    "Calm sea conditions naturally suppress capillary waves, creating look-alike dark patches."
                )
            else:
                wind_class = "HIGH_WIND"
                wind_consistency = EvidenceConsistency.CONFLICTING
                wind_desc = (
                    f"ERA5 10m wind speed ({wind_speed_ms:.2f} m/s) exceeds 12.0 m/s. Wave breaking and turbulence "
                    "rapidly disperse oil into the water column, limiting slick retention."
                )
        else:
            wind_class = "UNKNOWN"
            wind_consistency = EvidenceConsistency.UNAVAILABLE
            wind_desc = "ERA5 atmospheric wind reanalysis collocated data is unavailable."

        evidence_list.append(
            EvidenceItem(
                modality=ModalityType.ERA5_ATMOSPHERIC_WIND,
                sensor="ECMWF ERA5 Atmospheric Reanalysis",
                acquisition_time_utc=sar_time.isoformat(),
                temporal_offset_hours=w_offset_h,
                signature=wind_class,
                confidence=1.0 if wind_speed_ms is not None else 0.0,
                consistency=wind_consistency,
                description=wind_desc,
                metrics={
                    "wind_speed_ms": wind_speed_ms,
                    "wind_direction_deg": wind_direction_deg,
                    "wind_classification": wind_class,
                },
            )
        )

        # 3. Ingest Sentinel-2 Optical Evidence
        optical_status = "optical_data_not_acquired"
        opt_consistency = EvidenceConsistency.UNAVAILABLE
        opt_signature = "not_acquired"
        opt_desc = "No Sentinel-2 optical coverage has been collocated or extracted for this candidate."
        opt_metrics: dict[str, Any] = {}
        opt_offset_h: float | None = None

        if optical_evidence:
            opt_time_str = optical_evidence.get("acquisition_timestamp") or optical_evidence.get("acquisition_time_utc", "")
            opt_offset_h = optical_evidence.get("temporal_offset_hours")
            cloud_frac = optical_evidence.get("cloud_coverage_fraction", 0.0)
            water_frac = optical_evidence.get("valid_water_fraction", 0.0)
            mean_ndci = optical_evidence.get("mean_ndci")
            p90_ndci = optical_evidence.get("p90_ndci")
            mean_ndti = optical_evidence.get("mean_ndti")
            swir_ratio = optical_evidence.get("mean_swir_ratio")

            opt_metrics = {
                "scene_id": optical_evidence.get("scene_id"),
                "cloud_coverage_pct": round(cloud_frac * 100, 1),
                "valid_water_pct": round(water_frac * 100, 1),
                "mean_ndci": mean_ndci,
                "p90_ndci": p90_ndci,
                "mean_ndti": mean_ndti,
                "mean_swir_ratio": swir_ratio,
            }

            if water_frac < 0.30 or cloud_frac > 0.70:
                optical_status = "cloud_obscured"
                opt_consistency = EvidenceConsistency.INCONCLUSIVE
                opt_signature = "cloud_obscuration"
                opt_desc = (
                    f"Sentinel-2 optical chip is obscured by cloud cover ({cloud_frac * 100:.1f}% clouds, "
                    f"only {water_frac * 100:.1f}% valid water pixels). Surface reflectance cannot be evaluated."
                )
            elif (p90_ndci is not None and p90_ndci >= self.ALGAL_BLOOM_NDCI_THRESHOLD) or (
                mean_ndci is not None and mean_ndci >= self.ALGAL_BLOOM_NDCI_THRESHOLD
            ):
                optical_status = "biogenic_lookalike_confirmed"
                opt_consistency = EvidenceConsistency.CONFLICTING
                opt_signature = PollutionSignature.ALGAE_BLOOM_SIGNATURE.value
                opt_desc = (
                    f"Sentinel-2 multispectral NDCI ({p90_ndci:.3f}) indicates elevated surface chlorophyll-a. "
                    "The SAR dark formation is physically consistent with a biogenic algal film."
                )
            elif swir_ratio is not None and swir_ratio > 0.40:
                optical_status = "multi_sensor_slick_concordance"
                opt_consistency = EvidenceConsistency.SUPPORTING
                opt_signature = PollutionSignature.OIL_LIKE_SIGNATURE.value
                opt_desc = (
                    "Sentinel-2 surface reflectance shows a contrast with elevated SWIR ratio "
                    f"({swir_ratio:.2f}) and low chlorophyll-a (NDCI <= 0.0). Consistent with a "
                    "surface film; on its own it does not identify what the film is."
                )
            else:
                optical_status = "algal_bloom_excluded"
                opt_consistency = EvidenceConsistency.SUPPORTING
                opt_signature = "clean_water_algae_ruled_out"
                opt_desc = (
                    f"Sentinel-2 surface reflectance shows clear water ({water_frac * 100:.1f}% clear) with negative "
                    f"NDCI ({mean_ndci if mean_ndci is not None else 0.0:.3f}); this does not support an algal bloom."
                )

            evidence_list.append(
                EvidenceItem(
                    modality=ModalityType.OPTICAL_SENTINEL_2,
                    sensor=f"Sentinel-2 MSI Level-2A ({optical_evidence.get('scene_id', 'granule')[:25]}...)",
                    acquisition_time_utc=str(opt_time_str),
                    temporal_offset_hours=opt_offset_h,
                    signature=opt_signature,
                    confidence=0.85 if optical_status != "cloud_obscured" else 0.30,
                    consistency=opt_consistency,
                    description=opt_desc,
                    metrics=opt_metrics,
                )
            )

        # 4. Multi-Sensor Evidence Synthesis & Agreement Scoring
        if not sar_is_positive:
            concordance_level = ConcordanceLevel.NO_ANOMALY
            concordance_score = sar_confidence
            summary = "No anomalous radar damping detected across the evaluated cell."
            action = "No review required. Baseline clean ocean surface."
        elif optical_status == "biogenic_lookalike_confirmed":
            concordance_level = ConcordanceLevel.BIOGENIC_LOOKALIKE
            concordance_score = 0.15
            summary = (
                "SAR dark formation is consistent with a natural biogenic algal film: the simulated Sentinel-2 "
                f"product shows elevated chlorophyll-a (P90 NDCI = {opt_metrics.get('p90_ndci', 0.0):.3f})."
            )
            action = "Consider rejecting candidate as 'rejected_lookalike'; the optical input is simulated."
        elif wind_class == "LOW_WIND":
            concordance_level = ConcordanceLevel.CALM_WATER_AMBIGUITY
            concordance_score = 0.32
            summary = (
                f"SAR candidate was detected under low-wind calm sea conditions ({wind_speed_ms:.2f} m/s < 3.0 m/s). "
                "Natural absence of wind stress produces specular dark patches resembling oil slicks."
            )
            action = "Inspect high-resolution imagery and wind direction before decision; calm-water look-alike is possible."
        elif wind_class == "HIGH_WIND":
            concordance_level = ConcordanceLevel.DISPERSED_HIGH_WIND
            concordance_score = 0.25
            summary = (
                f"Candidate detected under elevated wind speed ({wind_speed_ms:.2f} m/s > 12.0 m/s). "
                "Intense mechanical wave action causes rapid physical dispersion."
            )
            action = "Review for potential sub-surface or ephemeral dispersion signature."
        elif optical_status == "multi_sensor_slick_concordance":
            concordance_level = ConcordanceLevel.MULTI_SENSOR_CONCORDANCE
            concordance_score = 0.92
            summary = (
                f"Rule-based multi-sensor concordance: SAR damping score (p_oil = {sar_confidence * 100:.1f}%) "
                f"and a simulated Sentinel-2 reflectance anomaly under favorable wind ({wind_speed_ms:.1f} m/s). "
                "This is a rule output over simulated optical inputs, not a calibrated probability."
            )
            action = "Rule-based screening flag only. Confirm with independent observations; this does not attribute responsibility to a vessel."
        elif optical_status == "algal_bloom_excluded":
            concordance_level = ConcordanceLevel.SAR_WIND_SUPPORTED
            concordance_score = 0.84
            summary = (
                f"SAR dark formation (p_oil = {sar_confidence * 100:.1f}%) with diagnostic wind ({wind_speed_ms:.1f} m/s). "
                "The simulated Sentinel-2 product is consistent with clear water and does not support an algal bloom look-alike (NDCI <= 0.0)."
            )
            action = "Rule-based support only; awaiting analyst confirmation."
        elif wind_class == "WITHIN_SCREENING_RANGE":
            concordance_level = ConcordanceLevel.SAR_WIND_SUPPORTED
            concordance_score = 0.72
            summary = (
                f"SAR dark formation (p_oil = {sar_confidence * 100:.1f}%) supported by diagnostic wind ({wind_speed_ms:.1f} m/s). "
                "Optical confirmation pending or obstructed by clouds."
            )
            action = "Eligible candidate awaiting analyst review. Consider querying alternate Sentinel-2 passes."
        else:
            concordance_level = ConcordanceLevel.SAR_ONLY_UNCONFIRMED
            concordance_score = 0.55
            summary = f"SAR detection (p_oil = {sar_confidence * 100:.1f}%) without collocated wind or optical confirmation."
            action = "Analyst review required; collateral environmental evidence unavailable."

        return MultiSensorAssessment(
            candidate_id=candidate_id,
            latitude=latitude,
            longitude=longitude,
            sar_screening_status=screening_status,
            wind_classification=wind_class,
            optical_verification_status=optical_status,
            concordance_score=concordance_score,
            concordance_level=concordance_level,
            triangulation_summary=summary,
            recommended_action=action,
            evidence_items=evidence_list,
        )
