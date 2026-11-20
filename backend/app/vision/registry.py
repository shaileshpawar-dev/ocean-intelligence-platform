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
from app.vision.sar_detector_v2 import SAROilSlickDetectorV2
from app.vision.yolo_detector import YOLODetector

logger = get_logger(__name__)

_image_detector: BaseDetector | None = None
_sar_detector: SARDarkFormationDetector | None = None
_sar_v2_detector: BaseDetector | None = None
_sar_v2_2_detector: BaseDetector | None = None


def get_image_detector(force: str | None = None) -> BaseDetector:
    """Return the configured detector for optical imagery.

    Args:
        force: Override the configured backend (``"yolo"``, ``"yolo-v2"``, or ``"mock"``).
            Used by tests.
    """
    global _image_detector
    backend = force or settings.detector_backend
    if _image_detector is not None and force is None:
        return _image_detector

    detector: BaseDetector
    if backend in ("yolo", "yolo-v2"):
        if backend == "yolo-v2" or settings.yolo_active_version == "v2":
            candidate = YOLODetector(
                model_path=settings.yolo_v2_model_path or settings.yolo_model_path,
                version="yolov8-v2" if settings.yolo_v2_model_path else "yolov8m-best",
            )
        else:
            candidate = YOLODetector()

        if candidate.is_available:
            detector = candidate
        else:
            logger.warning(
                "detector_fallback_to_mock",
                extra={
                    "requested": backend,
                    "reason": "checkpoint or ultralytics missing",
                },
            )
            detector = MockDetector()
    else:
        detector = MockDetector()

    if force is None:
        _image_detector = detector
    return detector


def get_sar_detector(force: str | None = None) -> BaseDetector:
    """Return the SAR dark-formation detector singleton.

    By default returns the baseline rule-based SARDarkFormationDetector (v1).
    When configured with ``sar_model_version = "v2"`` or ``force = "sar-v2"``,
    returns the deep-learning SAROilSlickDetectorV2.
    When configured with ``sar_model_version = "v2.2"`` or ``force = "sar-v2.2"``,
    returns SAROilSlickDetectorV2 configured with the V2.2 clean checkpoint.
    """
    global _sar_detector, _sar_v2_detector, _sar_v2_2_detector
    version = force or settings.sar_model_version
    if version in ("v2.2", "sar-v2.2"):
        if _sar_v2_2_detector is None or force is not None:
            _sar_v2_2_detector = SAROilSlickDetectorV2(
                model_path=settings.sar_v2_2_model_path,
                name="sar-oil-slick-v2.2",
                version="2.2.0-experimental",
            )
        return _sar_v2_2_detector

    if version in ("v2", "sar-v2"):
        if _sar_v2_detector is None or force is not None:
            _sar_v2_detector = SAROilSlickDetectorV2()
        return _sar_v2_detector

    if _sar_detector is None or force is not None:
        _sar_detector = SARDarkFormationDetector()
    return _sar_detector


def get_sar_v2_detector() -> BaseDetector:
    """Convenience accessor for the experimental V2 SAR detector."""
    return get_sar_detector(force="sar-v2")


def get_sar_v2_2_detector() -> BaseDetector:
    """Convenience accessor for the experimental V2.2 clean SAR detector."""
    return get_sar_detector(force="sar-v2.2")


def get_wind_aware_screener(detector: BaseDetector | None = None) -> Any:
    """Return an experimental wind-aware candidate screener combining SAR with ERA5."""
    from app.vision.wind_screener import WindAwareSARScreener

    det = detector or get_sar_detector()
    return WindAwareSARScreener(detector=det)


def reset_detectors() -> None:
    """Clear cached detectors. Used between tests."""
    global _image_detector, _sar_detector, _sar_v2_detector, _sar_v2_2_detector
    _image_detector = None
    _sar_detector = None
    _sar_v2_detector = None
    _sar_v2_2_detector = None


def describe_all() -> list[dict]:
    """Metadata for every detector, for the /models endpoint."""
    return [
        get_image_detector().describe(),
        get_sar_detector(force="v1").describe(),
        get_sar_v2_detector().describe(),
        get_sar_v2_2_detector().describe(),
    ]
