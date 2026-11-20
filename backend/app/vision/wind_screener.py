"""Environmental Context and Wind-Aware Candidate Screening Layer.

Combines SAR dark-formation texture classifications with ECMWF ERA5 10m wind fields
to evaluate physical radar damping credibility without modifying raw model confidence.

Physical Principles:
--------------------
- At low winds (< 3.0 m/s): Surface micro-roughness is absent due to lack of wind stress.
  Natural calm water cells, biogenic films, and wind shadows mimic petroleum damping.
- Within screening range (3.0 - 12.0 m/s): Capillary and short gravity waves (Bragg waves)
  are fully developed on clean sea, while oil films selectively damp them, creating
  maximum radar contrast.
- At high winds (> 12.0 m/s): Wave breaking and vertical turbulence disperse slicks into
  droplets, rapidly mixing them into the water column and obscuring surface signatures.

Scientific References:
---------------------
- Scott (1986), "The effect of surface active materials on waves and ripples",
  Proceedings of the Royal Society of London.
- Alpers et al. (1991), "On the detectability of marine oil spills by airborne and
  spaceborne synthetic aperture radar", IEEE TGRS.
- Yang & Singha (2024), International Journal of Remote Sensing, DOI: 10.1080/01431161.2024.2321468.
- Yang & Singha (2025), Earth System Science Data, DOI: 10.5194/essd-17-6807-2025.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import PollutionSignature
from app.vision.base import BaseDetector, Detection
from app.vision.era5_client import ERA5Record, ERA5Service

logger = get_logger(__name__)


class WindClassification(str, Enum):
    LOW_WIND = "LOW_WIND"  # < 3.0 m/s
    WITHIN_SCREENING_RANGE = "WITHIN_SCREENING_RANGE"  # 3.0 - 12.0 m/s
    HIGH_WIND = "HIGH_WIND"  # > 12.0 m/s
    UNKNOWN = "UNKNOWN"


class ScreeningStatus(str, Enum):
    # Core 3-state review-aware classification (Phase 13.1)
    CANDIDATE_REQUIRES_REVIEW = "candidate_requires_review"
    LOW_WIND_AMBIGUITY_REVIEW = "low_wind_ambiguity_review"
    HIGH_WIND_AMBIGUITY_REVIEW = "high_wind_ambiguity_review"
    NO_CANDIDATE_DETECTED = "no_candidate_detected"

    # Legacy Phase 13 statuses (preserved for backwards compatibility)
    CANDIDATE_SCREENED_POSITIVE = "candidate_screened_positive"
    CANDIDATE_FLAGGED_LOW_WIND = "candidate_flagged_low_wind"
    CANDIDATE_FLAGGED_HIGH_WIND = "candidate_flagged_high_wind"
    NO_SLICK_DETECTED = "no_slick_detected"


class WindAwareSARScreener:
    """Combines SAR detector inference with environmental ERA5 wind context.

    Preserves raw model outputs and confidences without arbitrary post-hoc math,
    surfacing structured environmental classifications and screening guidance.
    """

    def __init__(
        self,
        detector: BaseDetector | None = None,
        era5_service: ERA5Service | None = None,
        low_wind_threshold_ms: float = 3.0,
        high_wind_threshold_ms: float = 12.0,
    ) -> None:
        from app.vision.registry import get_sar_detector

        self.detector = detector or get_sar_detector(force="v1")
        self.era5_service = era5_service or ERA5Service()
        self.low_wind_threshold_ms = low_wind_threshold_ms
        self.high_wind_threshold_ms = high_wind_threshold_ms

    def screen(
        self,
        payload: Any,
        latitude: float | None = None,
        longitude: float | None = None,
        timestamp_iso: str | None = None,
        is_coastal: bool = False,
        patch_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute wind-aware candidate screening.

        Args:
            payload: Image path, numpy array, PIL Image, or dictionary.
            latitude: Target latitude (WGS84).
            longitude: Target longitude (WGS84).
            timestamp_iso: UTC acquisition timestamp in ISO format.
            is_coastal: Whether cell is located in coastal or near-shore zone.
            patch_id: Optional unique cache/patch identifier.
            **kwargs: Extra parameters passed to the detector.

        Returns:
            Dictionary matching the Phase 13 environmental-context schema.
        """
        # Extract metadata from payload if passed as dict
        if isinstance(payload, dict):
            latitude = latitude if latitude is not None else payload.get("latitude")
            longitude = longitude if longitude is not None else payload.get("longitude")
            timestamp_iso = timestamp_iso or payload.get("timestamp_iso") or payload.get("start_time")
            is_coastal = is_coastal or payload.get("is_coastal", False)
            patch_id = patch_id or payload.get("image_name") or payload.get("image") or payload.get("tag")

        # 1. Execute underlying detector (raw model output)
        detections: list[Detection] = self.detector.predict(payload, **kwargs)
        det = detections[0] if detections else None

        model_name = getattr(self.detector, "name", "unknown_detector")
        model_version = getattr(self.detector, "version", "unknown_version")

        if det is None:
            return {
                "model_prediction": "no_detection",
                "model_version": model_version,
                "model_confidence": 0.0,
                "confidence_is_calibrated": False,
                "wind_context": {
                    "source": "none",
                    "wind_speed_ms": None,
                    "wind_direction_degrees": None,
                    "classification": WindClassification.UNKNOWN.value,
                    "quality_status": "missing",
                },
                "environmental_warnings": ["Detector returned no detections."],
                "final_screening_status": ScreeningStatus.NO_CANDIDATE_DETECTED.value,
                "three_state_status": ScreeningStatus.NO_CANDIDATE_DETECTED.value,
                "retained_for_analyst_review": False,
            }

        signature = det.signature
        confidence = float(det.confidence)
        is_calibrated = bool(det.confidence_is_calibrated)

        # 2. Retrieve ERA5 wind context
        wind_record: ERA5Record | None = None
        if patch_id or (latitude is not None and longitude is not None):
            lookup_id = patch_id or f"coord_{latitude:.4f}_{longitude:.4f}"
            lat_val = latitude or 0.0
            lon_val = longitude or 0.0
            ts_val = timestamp_iso or "2019-01-01T00:00:00Z"
            try:
                wind_record = self.era5_service.collocate_patch(
                    patch_id=lookup_id,
                    lat=lat_val,
                    lon=lon_val,
                    timestamp_iso=ts_val,
                    is_coastal=is_coastal,
                )
            except Exception as e:
                logger.warning("era5_collocation_failed", extra={"error": str(e)})
                wind_record = None

        # 3. Classify wind and generate environmental warnings
        warnings: list[str] = []
        wind_dict: dict[str, Any] = {
            "source": "none",
            "wind_speed_ms": None,
            "wind_direction_degrees": None,
            "classification": WindClassification.UNKNOWN.value,
            "quality_status": "missing",
        }

        w_class = WindClassification.UNKNOWN
        w_speed = None

        if wind_record and wind_record.quality_status != "missing":
            w_speed = wind_record.wind_speed_ms
            wind_dict = {
                "source": wind_record.source,
                "dataset_version": wind_record.dataset_version,
                "wind_speed_ms": w_speed,
                "wind_direction_degrees": wind_record.wind_direction_deg,
                "grid_coordinates": [wind_record.grid_latitude, wind_record.grid_longitude],
                "temporal_offset_minutes": wind_record.temporal_offset_minutes,
                "grid_distance_km": wind_record.grid_distance_km,
                "is_coastal": wind_record.is_coastal,
                "sampling_method": wind_record.sampling_method,
                "quality_status": wind_record.quality_status,
            }

            if w_speed < self.low_wind_threshold_ms:
                w_class = WindClassification.LOW_WIND
                warnings.append(
                    f"Low wind speed ({w_speed:.2f} m/s < {self.low_wind_threshold_ms} m/s): "
                    "Capillary wave suppression prevents definitive radar separation between "
                    "oil slicks and natural look-alikes (calm cells, biogenic films, wind shadows). "
                    "Candidate requires optical or in-situ verification."
                )
            elif w_speed > self.high_wind_threshold_ms:
                w_class = WindClassification.HIGH_WIND
                warnings.append(
                    f"High wind speed ({w_speed:.2f} m/s > {self.high_wind_threshold_ms} m/s): "
                    "Strong wind and wave breaking disperse mineral oil into the water column. "
                    "Surface film retention is physically unlikely."
                )
            else:
                w_class = WindClassification.WITHIN_SCREENING_RANGE
                warnings.append(
                    f"Optimal wind speed ({w_speed:.2f} m/s within [{self.low_wind_threshold_ms}, "
                    f"{self.high_wind_threshold_ms}] m/s): "
                    "Sea surface supports Bragg capillary waves; radar damping contrast is diagnostic."
                )

            if wind_record.is_coastal:
                warnings.append(
                    "Coastal proximity notice: ERA5 grid resolution (~31 km) may not fully resolve "
                    "sub-grid coastal topography and local island wind shadows."
                )
        else:
            warnings.append(
                "Wind context unverified: Missing ERA5 reanalysis for target coordinates/time. "
                "Candidate screening operates without environmental wind gating."
            )

        wind_dict["classification"] = w_class.value

        # 4. Formulate candidate detection & review-aware status
        # A candidate is detected if the CNN identifies an oil-like signature (or V1 heuristic anomaly)
        is_candidate_oil = False
        if signature == PollutionSignature.OIL_LIKE_SIGNATURE:
            is_candidate_oil = True
        elif signature == PollutionSignature.DARK_FORMATION:
            # Baseline V1 outputs DARK_FORMATION for significant depressions
            # For V2/V2.1/V2.2 CNNs, DARK_FORMATION is sub-threshold (0.25 <= p < 0.50), which is NOT a positive candidate
            p_oil_cand = det.extra.get("p_oil_candidate") if det.extra else None
            if p_oil_cand is not None:
                is_candidate_oil = bool(p_oil_cand >= 0.50)
            elif getattr(self.detector, "version", "").startswith("1.") or confidence >= 0.50:
                is_candidate_oil = True

        if not is_candidate_oil or signature == PollutionSignature.NO_ANOMALY:
            screening_status = ScreeningStatus.NO_CANDIDATE_DETECTED
            retained_for_review = False
        else:
            retained_for_review = True
            if w_class == WindClassification.LOW_WIND:
                screening_status = ScreeningStatus.LOW_WIND_AMBIGUITY_REVIEW
            elif w_class == WindClassification.HIGH_WIND:
                screening_status = ScreeningStatus.HIGH_WIND_AMBIGUITY_REVIEW
            else:
                screening_status = ScreeningStatus.CANDIDATE_REQUIRES_REVIEW

        # Retain original detector caveats
        for c in det.caveats:
            if c not in warnings:
                warnings.append(c)

        return {
            "model_prediction": str(signature.value if hasattr(signature, "value") else signature),
            "model_version": model_version,
            "model_confidence": round(confidence, 4),
            "confidence_is_calibrated": is_calibrated,
            "wind_context": wind_dict,
            "environmental_warnings": warnings,
            "final_screening_status": screening_status.value,
            "three_state_status": screening_status.value,
            "retained_for_analyst_review": retained_for_review,
        }
