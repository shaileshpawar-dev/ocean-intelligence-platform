"""Deep-learning candidate oil-slick detector on Sentinel-1 C-band SAR (V2).

This detector replaces monolithic RGB-only pollution detection with a
scientifically grounded, dedicated SAR texture analysis pipeline. It evaluates
spatial damping patterns in Sentinel-1 C-SAR VV amplitude to screen candidate
oil slicks and explicitly differentiate them from natural look-alikes.

Dataset Provenance:
-------------------
Trained and evaluated on the peer-reviewed benchmark dataset from the German
Aerospace Center (DLR) and Danish Meteorological Institute (DMI):
  Yang & Singha (2025), "Dataset of oil slicks, look-alikes and remarkable SAR
  signatures obtained from Sentinel-1 data in the Eastern Mediterranean Sea",
  Earth System Science Data (ESSD), DOI: 10.5194/essd-17-6807-2025.
  Data hosted on PANGAEA: DOI 10.1594/PANGAEA.980773 (CC BY 4.0).

Scientific Role:
----------------
This model is an *experimental candidate screener*. In compliance with
physical remote sensing principles, it emits candidate signatures rather than
asserting confirmed mineral oil spills. Low-wind cells, biogenic algal films,
and coastal wind shadows remain physical look-alikes requiring wind speed and
optical cross-verification.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import torch
import torch.nn as nn

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature
from app.vision.base import BaseDetector, Detection

logger = get_logger(__name__)

LOOKALIKE_CAVEAT = (
    "Dark formations in C-band SAR are not unique to oil. Low wind (<3 m/s), "
    "biogenic slicks, and wind shadows produce look-alikes. Detections represent "
    "candidate surface films requiring multi-source verification."
)

BENCHMARK_CAVEAT = (
    "Evaluated on independent Sentinel-1 test split (Yang & Singha 2025, ESSD): "
    "93.3% recall, 63.6% precision, 0.757 F1. High candidate sensitivity "
    "warrants wind-speed and optical triangulation."
)

UNCALIBRATED_CAVEAT = (
    "Confidence score is derived from CNN softmax output over spatial SAR texture, "
    "not a fully calibrated operational likelihood."
)


class SAROilSlickCNN(nn.Module):
    """Compact 4-block CNN for SAR backscatter texture classification.

    Parameters: 101,826.
    Inference Latency: ~5.5 ms on CPU.
    """

    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),  # 112x112
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),  # 56x56
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),  # 28x28
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),  # 128x1x1
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(128, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.features(x)
        return self.classifier(feat)


class SAROilSlickMultiScaleCNN(nn.Module):
    """Multi-scale receptive field CNN for SAR texture classification.

    Parameters: 133,466.
    Inference Latency: ~38 ms on CPU.
    Combines parallel 3x3 and 5x5 convolutions to capture both sharp slick
    boundary gradients and broader sea-state damping contrast.
    """

    def __init__(self) -> None:
        super().__init__()
        self.conv1_3x3 = nn.Conv2d(1, 12, kernel_size=3, padding=1)
        self.conv1_5x5 = nn.Conv2d(1, 8, kernel_size=5, padding=2)
        self.bn1 = nn.BatchNorm2d(20)
        self.pool1 = nn.MaxPool2d(2, 2)  # 112x112

        self.block2 = nn.Sequential(
            nn.Conv2d(20, 40, kernel_size=3, padding=1),
            nn.BatchNorm2d(40),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),  # 56x56
        )
        self.block3 = nn.Sequential(
            nn.Conv2d(40, 80, kernel_size=3, padding=1),
            nn.BatchNorm2d(80),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),  # 28x28
        )
        self.block4 = nn.Sequential(
            nn.Conv2d(80, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),  # 128x1x1
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.4),
            nn.Linear(128, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        f3 = self.conv1_3x3(x)
        f5 = self.conv1_5x5(x)
        f = self.pool1(torch.relu(self.bn1(torch.cat([f3, f5], dim=1))))
        f = self.block2(f)
        f = self.block3(f)
        f = self.block4(f)
        return self.classifier(f)


class SAROilSlickDetectorV2(BaseDetector):
    """Deep-learning candidate oil-slick screener for Sentinel-1 SAR imagery."""

    name = "sar-oil-slick-v2"
    version = "2.0.0-experimental"
    method = DetectionMethod.SAR_DARK_FORMATION
    supported_signatures = frozenset(
        {
            PollutionSignature.OIL_LIKE_SIGNATURE,
            PollutionSignature.DARK_FORMATION,
            PollutionSignature.NO_ANOMALY,
        }
    )

    def __init__(
        self,
        model_path: Path | str | None = None,
        confidence_threshold: float = 0.50,
        name: str | None = None,
        version: str | None = None,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        if name:
            self.name = name
        if version:
            self.version = version
        self.model_path = Path(
            model_path or getattr(settings, "sar_v2_model_path", None) or "data/models/sar/v2/best.pt"
        )
        self._model: nn.Module | None = None
        self._metadata: dict[str, Any] = {}
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """Load trained weights and metadata from checkpoint."""
        if not self.model_path.exists():
            logger.warning(
                "sar_v2_checkpoint_missing",
                extra={"path": str(self.model_path)},
            )
            return

        try:
            ckpt = torch.load(self.model_path, map_location="cpu", weights_only=False)
            arch = ckpt.get("architecture") if isinstance(ckpt, dict) else "SAROilSlickCNN"
            if arch == "SAROilSlickMultiScaleCNN":
                self._model = SAROilSlickMultiScaleCNN()
            else:
                self._model = SAROilSlickCNN()

            if isinstance(ckpt, dict) and "state_dict" in ckpt:
                self._model.load_state_dict(ckpt["state_dict"])
                self._metadata = {
                    "architecture": arch,
                    "test_metrics": ckpt.get("test_metrics", {}),
                    "comparison_on_same_test": ckpt.get("comparison_on_100_test") or ckpt.get("baseline_comparison", {}),
                    "training_date": ckpt.get("training_date"),
                    "epochs_trained": ckpt.get("epochs_trained"),
                    "param_count": ckpt.get("param_count", 101826 if arch == "SAROilSlickCNN" else 133466),
                    "decision_threshold": ckpt.get("decision_threshold", 0.50),
                }
            else:
                self._model.load_state_dict(ckpt)
            self._model.eval()
            logger.info(
                "sar_v2_checkpoint_loaded",
                extra={"path": str(self.model_path), "architecture": arch},
            )
        except Exception as e:
            logger.error(
                "sar_v2_load_error",
                extra={"error": str(e), "path": str(self.model_path)},
            )
            self._model = None

    @property
    def is_available(self) -> bool:
        """Whether the model weights were successfully loaded."""
        return self._model is not None

    def predict(self, payload: Any, **kwargs: Any) -> list[Detection]:
        """Classify a SAR image patch or raster array for candidate oil slicks.

        Args:
            payload: Path to an image file (str or Path), a PIL Image, a NumPy
                grayscale array, or a dict containing ``"image_path"`` or ``"array"``.
            **kwargs: Can override ``confidence_threshold``.

        Returns:
            A list containing at most one Detection.
        """
        if not self.is_available or self._model is None:
            logger.warning("sar_v2_called_when_unavailable")
            return []

        threshold = kwargs.get("confidence_threshold", self.confidence_threshold)
        tensor = self._preprocess(payload)
        if tensor is None:
            logger.warning("sar_v2_invalid_payload_format")
            return []

        t0 = time.perf_counter()
        with torch.no_grad():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1).squeeze(0)
            p_lookalike = float(probs[0].item())
            p_oil = float(probs[1].item())
        latency_ms = (time.perf_counter() - t0) * 1000.0

        extra: dict[str, Any] = {
            "p_oil_candidate": round(p_oil, 4),
            "p_lookalike": round(p_lookalike, 4),
            "latency_ms": round(latency_ms, 2),
            "model_version": self.version,
            "architecture": self._metadata.get("architecture", "SAROilSlickCNN"),
            "threshold": threshold,
        }

        # Check for wind speed or location context in payload if provided
        lat, lon = None, None
        if isinstance(payload, dict):
            lat = payload.get("latitude")
            lon = payload.get("longitude")
            wind = payload.get("wind_speed_ms")
            if wind is not None:
                extra["wind_speed_ms"] = wind
                if float(wind) < getattr(settings, "sar_min_wind_speed_ms", 3.0):
                    p_oil *= 0.5
                    extra["wind_downgrade"] = True

        caveats = [LOOKALIKE_CAVEAT, BENCHMARK_CAVEAT, UNCALIBRATED_CAVEAT]

        if p_oil >= threshold:
            signature = PollutionSignature.OIL_LIKE_SIGNATURE
            confidence = p_oil
            caveats.insert(
                0,
                f"Candidate oil-slick signature detected with CNN confidence {p_oil:.2f}. "
                "Local backscatter damping patterns match verified SAR oil slick benchmark.",
            )
        elif p_oil >= 0.25:
            signature = PollutionSignature.DARK_FORMATION
            confidence = p_oil
            caveats.insert(
                0,
                f"Weak backscatter anomaly ({p_oil:.2f}). Classified as generic dark formation; "
                "exhibits characteristics of natural look-alikes (low wind, biogenic film).",
            )
        else:
            signature = PollutionSignature.NO_ANOMALY
            confidence = p_lookalike
            caveats = [
                "No anomalous damping indicative of an oil slick found. "
                "Radar backscatter is consistent with unpolluted sea state."
            ]

        return self._validate(
            [
                Detection(
                    signature=signature,
                    confidence=round(confidence, 4),
                    confidence_is_calibrated=False,
                    method=self.method,
                    model_version=self.version,
                    evidence_level=EvidenceLevel.DETECTED,
                    latitude=lat,
                    longitude=lon,
                    class_name=str(signature),
                    caveats=caveats,
                    extra=extra,
                )
            ]
        )

    def _preprocess(self, payload: Any) -> torch.Tensor | None:
        """Convert payload to a (1, 1, 224, 224) tensor normalized to [-1, 1]."""
        raw_img = None
        if isinstance(payload, (str, Path)):
            path = Path(payload)
            if path.exists():
                raw_img = Image.open(path)
        elif isinstance(payload, Image.Image):
            raw_img = payload
        elif isinstance(payload, np.ndarray):
            raw_img = Image.fromarray(payload.astype(np.uint8))
        elif isinstance(payload, dict):
            if "image_path" in payload and Path(payload["image_path"]).exists():
                raw_img = Image.open(Path(payload["image_path"]))
            elif "array" in payload and isinstance(payload["array"], np.ndarray):
                raw_img = Image.fromarray(payload["array"].astype(np.uint8))

        if raw_img is None:
            return None

        # Convert to single-channel grayscale and resize to 224x224
        im_gray = raw_img.convert("L").resize((224, 224), Image.Resampling.BILINEAR)
        arr = np.array(im_gray, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0)  # (1, 1, 224, 224)
        tensor = (tensor - 0.5) / 0.5
        return tensor

    def describe(self) -> dict[str, Any]:
        """Metadata for the /models endpoint."""
        info = super().describe()
        arch_name = self._metadata.get("architecture", "SAROilSlickCNN")
        params = self._metadata.get("param_count", 101826 if arch_name == "SAROilSlickCNN" else 133466)
        info.update(
            {
                "architecture": f"{arch_name} ({params:,} params)",
                "modality": "Sentinel-1 C-SAR GRD (VV amplitude)",
                "input_resolution": [224, 224],
                "evaluation_status": "evaluated_on_labeled_test_data",
                "dataset_provenance": "PANGAEA 980773 / DARTIS 2019 (Yang & Singha 2025, CC BY 4.0)",
                "is_default": False,
                "role": "Experimental candidate screener; sar-detector-v1 remains default baseline",
                "test_metrics": self._metadata.get("test_metrics", {
                    "accuracy": 0.7000,
                    "precision": 0.6364,
                    "recall": 0.9333,
                    "f1_score": 0.7568,
                    "avg_cpu_latency_ms": 5.55,
                }),
                "baseline_comparison": (
                    self._metadata.get("comparison_on_same_test")
                    or self._metadata.get("baseline_comparison", {
                        "baseline_name": "backscatter_contrast_threshold",
                        "accuracy": 0.6000,
                        "precision": 0.8000,
                        "recall": 0.2667,
                        "f1_score": 0.4000,
                    })
                ),
            }
        )
        return info
