"""Deterministic stand-in detector for demo mode, tests and CI.

Every detection it produces is tagged ``EvidenceLevel.SIMULATED`` and carries
an unmissable caveat, so a demo can never be mistaken for a real observation.
Output is derived from a hash of the input path, making it reproducible.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature
from app.vision.base import BaseDetector, Detection

SIMULATED_CAVEAT = (
    "SIMULATED OUTPUT. Produced by the mock detector for demonstration "
    "purposes. This is not a real detection and describes no real image."
)

_SIGNATURES = [
    PollutionSignature.OIL_LIKE_SIGNATURE,
    PollutionSignature.ALGAE_BLOOM_SIGNATURE,
    PollutionSignature.PLASTIC_DEBRIS_SIGNATURE,
    PollutionSignature.SURFACE_ANOMALY,
]


class MockDetector(BaseDetector):
    """Reproducible fake detector. Never returns anything real."""

    name = "mock-detector"
    version = "sim-1.0.0"
    method = DetectionMethod.SIMULATED
    supported_signatures = frozenset(_SIGNATURES)

    def predict(self, payload: Any, **kwargs: Any) -> list[Detection]:
        """Derive a stable pseudo-detection from a hash of ``payload``."""
        digest = hashlib.sha256(str(payload).encode()).digest()
        count = digest[0] % 3  # 0, 1 or 2 detections
        geo_bounds: list[float] | None = kwargs.get("geo_bounds")

        detections: list[Detection] = []
        for i in range(count):
            offset = i * 6
            signature = _SIGNATURES[digest[offset + 1] % len(_SIGNATURES)]
            conf = 0.35 + (digest[offset + 2] / 255.0) * 0.5
            x1 = (digest[offset + 3] / 255.0) * 300
            y1 = (digest[offset + 4] / 255.0) * 300
            bbox = [x1, y1, x1 + 90, y1 + 70]

            lat = lon = None
            if geo_bounds:
                lon = (geo_bounds[0] + geo_bounds[2]) / 2
                lat = (geo_bounds[1] + geo_bounds[3]) / 2

            detections.append(
                Detection(
                    signature=signature,
                    confidence=round(conf, 4),
                    confidence_is_calibrated=False,
                    method=self.method,
                    model_version=self.version,
                    evidence_level=EvidenceLevel.SIMULATED,
                    bbox=bbox,
                    latitude=lat,
                    longitude=lon,
                    area_pixels=(90 * 70),
                    class_name=str(signature),
                    caveats=[SIMULATED_CAVEAT],
                    extra={"simulated": True},
                )
            )
        return self._validate(detections)
