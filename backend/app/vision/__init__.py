"""Computer vision layer: detector abstraction and implementations."""

from app.vision.base import BaseDetector, Detection
from app.vision.mock_detector import MockDetector
from app.vision.registry import get_image_detector, get_sar_detector
from app.vision.sar_detector import SARDarkFormationDetector
from app.vision.yolo_detector import YOLODetector

__all__ = [
    "BaseDetector",
    "Detection",
    "MockDetector",
    "SARDarkFormationDetector",
    "YOLODetector",
    "get_image_detector",
    "get_sar_detector",
]
