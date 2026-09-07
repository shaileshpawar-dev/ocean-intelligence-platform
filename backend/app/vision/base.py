"""Detector abstraction.

Every detector in the platform returns :class:`Detection` objects and declares
which :class:`PollutionSignature` values it is *entitled* to emit. A detector
that has only seen C-band SAR must not be able to claim "plastic waste", and
the type system makes that explicit rather than relying on discipline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.base import utcnow
from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature


@dataclass(slots=True)
class Detection:
    """A single detector output.

    Attributes:
        signature: What kind of surface feature was found.
        confidence: Detector score in [0, 1].
        confidence_is_calibrated: Whether ``confidence`` is a calibrated
            probability. Heuristic detectors set this False, and the API
            surfaces it so a consumer never mistakes a score for a
            likelihood.
        bbox: ``[x1, y1, x2, y2]`` in pixel space, when applicable.
        geo_bbox: ``[min_lon, min_lat, max_lon, max_lat]`` in WGS84.
        caveats: Known failure modes for this specific detection, carried
            through to the API and the generated report.
    """

    signature: PollutionSignature
    confidence: float
    method: DetectionMethod
    model_version: str

    confidence_is_calibrated: bool = False
    evidence_level: EvidenceLevel = EvidenceLevel.DETECTED

    bbox: list[float] | None = None
    geo_bbox: list[float] | None = None
    latitude: float | None = None
    longitude: float | None = None

    area_pixels: int | None = None
    estimated_area_km2: float | None = None
    area_method: str | None = None

    class_id: int | None = None
    class_name: str | None = None
    detected_at: datetime = field(default_factory=utcnow)

    caveats: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for API responses and logging."""
        return {
            "signature": str(self.signature),
            "confidence": round(self.confidence, 4),
            "confidence_is_calibrated": self.confidence_is_calibrated,
            "method": str(self.method),
            "model_version": self.model_version,
            "evidence_level": str(self.evidence_level),
            "bbox": self.bbox,
            "geo_bbox": self.geo_bbox,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "area_pixels": self.area_pixels,
            "estimated_area_km2": self.estimated_area_km2,
            "area_method": self.area_method,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "detected_at": self.detected_at.isoformat(),
            "caveats": self.caveats,
            "extra": self.extra,
        }


class BaseDetector(ABC):
    """Interface every detector implements.

    Subclasses declare ``supported_signatures`` so callers can reject a claim
    the modality cannot support, and ``version`` so every persisted detection
    is traceable to the exact artefact that produced it.
    """

    name: str = "base"
    version: str = "0.0.0"
    method: DetectionMethod = DetectionMethod.MANUAL
    supported_signatures: frozenset[PollutionSignature] = frozenset()

    @abstractmethod
    def predict(self, payload: Any, **kwargs: Any) -> list[Detection]:
        """Run inference and return zero or more detections.

        Returning an empty list is a meaningful negative result, not a
        failure: it means the detector looked and found nothing.
        """

    @property
    def is_available(self) -> bool:
        """Whether the detector's runtime dependencies actually loaded."""
        return True

    def describe(self) -> dict[str, Any]:
        """Metadata for the /models endpoint and prediction logs."""
        return {
            "name": self.name,
            "version": self.version,
            "method": str(self.method),
            "available": self.is_available,
            "supported_signatures": sorted(str(s) for s in self.supported_signatures),
        }

    def _validate(self, detections: list[Detection]) -> list[Detection]:
        """Reject any detection whose signature this modality cannot support.

        This is the guardrail that would have prevented the original system
        from labelling SAR backscatter as "plastic_waste".
        """
        for det in detections:
            if det.signature not in self.supported_signatures:
                raise ValueError(
                    f"{self.name} v{self.version} emitted unsupported signature "
                    f"{det.signature!r}; supported: "
                    f"{sorted(str(s) for s in self.supported_signatures)}"
                )
        return detections
