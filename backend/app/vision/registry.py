"""Detector selection.

Keeps the choice of backend in configuration rather than in call sites, so a
future detector plugs in by registering here. Falls back to the mock detector
with a loud warning rather than crashing the application when the configured
backend cannot load -- an unavailable optional model must not take the
platform down.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.vision.base import BaseDetector
from app.vision.mock_detector import MockDetector
from app.vision.sar_detector import SARDarkFormationDetector
from app.vision.yolo_detector import YOLODetector

logger = get_logger(__name__)

_image_detector: BaseDetector | None = None
_sar_detector: SARDarkFormationDetector | None = None


def get_image_detector(force: str | None = None) -> BaseDetector:
    """Return the configured detector for optical imagery.

    Args:
        force: Override the configured backend (``"yolo"`` or ``"mock"``).
            Used by tests.
    """
    global _image_detector
    backend = force or settings.detector_backend
    if _image_detector is not None and force is None:
        return _image_detector

    detector: BaseDetector
    if backend == "yolo":
        candidate = YOLODetector()
        if candidate.is_available:
            detector = candidate
        else:
            logger.warning(
                "detector_fallback_to_mock",
                extra={
                    "requested": "yolo",
                    "reason": "checkpoint or ultralytics missing",
                },
            )
            detector = MockDetector()
    else:
        detector = MockDetector()

    if force is None:
        _image_detector = detector
    return detector


def get_sar_detector() -> SARDarkFormationDetector:
    """Return the SAR dark-formation detector singleton."""
    global _sar_detector
    if _sar_detector is None:
        _sar_detector = SARDarkFormationDetector()
    return _sar_detector


def reset_detectors() -> None:
    """Clear cached detectors. Used between tests."""
    global _image_detector, _sar_detector
    _image_detector = None
    _sar_detector = None


def describe_all() -> list[dict]:
    """Metadata for every detector, for the /models endpoint."""
    return [get_image_detector().describe(), get_sar_detector().describe()]
