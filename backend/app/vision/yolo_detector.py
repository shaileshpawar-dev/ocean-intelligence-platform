"""YOLO object detector for optical imagery.

Wraps the existing ``best.pt`` YOLOv8m checkpoint. The model is kept: it was
trained on labelled optical imagery and is the only component of the original
system that produces a genuine learned prediction. Two things changed:

1. **Geolocation.** The original assigned ``random.uniform(-30, 30)`` latitude
   to every detection. A detection is now geolocated only when the caller
   supplies the source image's geographic bounds; otherwise latitude and
   longitude stay ``None`` and a caveat says so. A detection with no known
   location is more useful than one with a fabricated location.
2. **Availability.** ``ultralytics`` is an optional dependency. If it or the
   checkpoint is missing the detector reports ``is_available = False`` and the
   application still starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature
from app.vision.base import BaseDetector, Detection

logger = get_logger(__name__)

#: Fallback map from the trained checkpoint's class ids to the platform's
#: signature vocabulary, used only when the checkpoint exposes no ``names``.
#: The raw trained label is preserved on ``Detection.class_name`` so nothing
#: is lost, while ``signature`` states the defensible claim.
#:
#: These four ids were read directly out of ``best.pt`` (ultralytics 8.4.41,
#: trained 2026-04-22, ``pollution.yaml``, 100 epochs at 640 px). Note that
#: **class 3 is ``chemical_pollution``, not ``marine_debris``** -- the original
#: notebook's ``CLASS_NAMES`` dict had it wrong, so every class-3 detection in
#: that system was reported under the wrong label.
DEFAULT_CLASS_MAP: dict[int, tuple[str, PollutionSignature]] = {
    0: ("oil_spill", PollutionSignature.OIL_LIKE_SIGNATURE),
    1: ("algae_bloom", PollutionSignature.ALGAE_BLOOM_SIGNATURE),
    2: ("plastic_waste", PollutionSignature.PLASTIC_DEBRIS_SIGNATURE),
    # A chemical identification is not derivable from RGB reflectance -- what
    # is actually visible is surface discolouration. The trained label is kept
    # on class_name; the signature stays at what optical imagery can support.
    3: ("chemical_pollution", PollutionSignature.SURFACE_ANOMALY),
}

#: How a trained label maps onto a defensible signature. Consulted first,
#: keyed by the checkpoint's own ``names``, so a retrained model with
#: reordered or additional classes is handled without editing ids.
LABEL_SIGNATURE_MAP: dict[str, PollutionSignature] = {
    "oil_spill": PollutionSignature.OIL_LIKE_SIGNATURE,
    "oil": PollutionSignature.OIL_LIKE_SIGNATURE,
    "algae_bloom": PollutionSignature.ALGAE_BLOOM_SIGNATURE,
    "algae": PollutionSignature.ALGAE_BLOOM_SIGNATURE,
    "plastic_waste": PollutionSignature.PLASTIC_DEBRIS_SIGNATURE,
    "plastic": PollutionSignature.PLASTIC_DEBRIS_SIGNATURE,
    "marine_debris": PollutionSignature.PLASTIC_DEBRIS_SIGNATURE,
    "chemical_pollution": PollutionSignature.SURFACE_ANOMALY,
}

CHEMICAL_CAVEAT = (
    "The checkpoint emitted the trained label 'chemical_pollution'. Optical "
    "reflectance cannot identify a chemical species; what is observable is "
    "surface discolouration. Reported as a surface anomaly, with the trained "
    "label preserved for traceability."
)

UNGEOREFERENCED_CAVEAT = (
    "No geographic bounds were supplied for the source image, so this "
    "detection is not geolocated. Pixel coordinates only."
)
UNCALIBRATED_CAVEAT = (
    "Confidence is the raw detector score. It has not been calibrated "
    "against a held-out set, so it is not a probability of correctness."
)


class YOLODetector(BaseDetector):
    """YOLOv8 detector over optical / RGB imagery."""

    name = "yolo-pollution-detector"
    method = DetectionMethod.YOLO_OPTICAL
    supported_signatures = frozenset(
        {
            PollutionSignature.OIL_LIKE_SIGNATURE,
            PollutionSignature.ALGAE_BLOOM_SIGNATURE,
            PollutionSignature.PLASTIC_DEBRIS_SIGNATURE,
            PollutionSignature.SURFACE_ANOMALY,
        }
    )

    def __init__(
        self,
        model_path: str | None = None,
        version: str = "yolov8m-best",
        conf_threshold: float | None = None,
    ) -> None:
        """Record the checkpoint path; loading is deferred to first use."""
        self.model_path = model_path or settings.yolo_model_path
        self.version = version
        self.conf_threshold = (
            conf_threshold
            if conf_threshold is not None
            else settings.detection_confidence_threshold
        )
        self._model: Any = None
        self._load_error: str | None = None
        self._names: dict[int, str] = {}

    # -- Lifecycle ---------------------------------------------------------
    def _load(self) -> Any:
        """Lazily load the checkpoint. Failures are recorded, not raised."""
        if self._model is not None or self._load_error is not None:
            return self._model
        if not self.model_path or not Path(self.model_path).exists():
            self._load_error = f"checkpoint not found: {self.model_path!r}"
            logger.warning("yolo_unavailable", extra={"reason": self._load_error})
            return None
        try:
            from ultralytics import YOLO

            self._model = YOLO(self.model_path)
            # Read the class names the checkpoint itself carries. Trusting a
            # hardcoded map is how the original system came to report class 3
            # as "marine_debris" when the model actually emits
            # "chemical_pollution".
            names = getattr(self._model, "names", None) or {}
            self._names = {int(k): str(v) for k, v in dict(names).items()}
            logger.info(
                "yolo_loaded",
                extra={"path": self.model_path, "classes": self._names},
            )
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.warning("yolo_unavailable", extra={"reason": self._load_error})
        return self._model

    @property
    def is_available(self) -> bool:
        """True once the checkpoint and ultralytics are both loadable."""
        return self._load() is not None

    @property
    def class_names(self) -> dict[int, str]:
        """Class ids to trained labels, read from the checkpoint."""
        self._load()
        return dict(self._names) or {i: n for i, (n, _) in DEFAULT_CLASS_MAP.items()}

    def resolve_class(self, cls_id: int) -> tuple[str, PollutionSignature]:
        """Map a predicted class id to its trained label and its signature.

        Resolution order, most to least trustworthy:

        1. the checkpoint's own ``names`` plus :data:`LABEL_SIGNATURE_MAP`
        2. :data:`DEFAULT_CLASS_MAP`, keyed by id
        3. an explicit unknown, reported as a bare surface anomaly

        An unrecognised label degrades to ``SURFACE_ANOMALY`` rather than
        being guessed into a specific claim.
        """
        label = self._names.get(cls_id)
        if label:
            signature = LABEL_SIGNATURE_MAP.get(label)
            if signature is not None:
                return label, signature
            logger.warning("yolo_unmapped_label", extra={"label": label})
            return label, PollutionSignature.SURFACE_ANOMALY
        if cls_id in DEFAULT_CLASS_MAP:
            return DEFAULT_CLASS_MAP[cls_id]
        return f"class_{cls_id}", PollutionSignature.SURFACE_ANOMALY

    def describe(self) -> dict[str, Any]:
        """Metadata plus the checkpoint's actual class list."""
        info = super().describe()
        info["class_names"] = self.class_names
        info["checkpoint"] = self.model_path
        return info

    # -- Inference ---------------------------------------------------------
    def predict(self, payload: Any, **kwargs: Any) -> list[Detection]:
        """Run detection on an image.

        Args:
            **kwargs: See ``geo_bounds`` and ``image_size`` below.
            payload: Path to an image file.
            geo_bounds: Optional ``[min_lon, min_lat, max_lon, max_lat]`` for
                the full image, enabling per-detection geolocation.
            image_size: Optional ``(width, height)``; read from the result
                when omitted.

        Returns:
            One :class:`Detection` per box above the confidence threshold.
        """
        model = self._load()
        if model is None:
            raise RuntimeError(
                f"YOLO detector unavailable ({self._load_error}). "
                "Set YOLO_MODEL_PATH and install ultralytics, or use "
                "DETECTOR_BACKEND=mock."
            )

        geo_bounds: list[float] | None = kwargs.get("geo_bounds")
        results = model(str(payload), conf=self.conf_threshold, verbose=False)[0]

        img_h, img_w = (None, None)
        if getattr(results, "orig_shape", None):
            img_h, img_w = results.orig_shape[0], results.orig_shape[1]

        detections: list[Detection] = []
        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            xyxy = [float(v) for v in box.xyxy[0].tolist()]

            class_name, signature = self.resolve_class(cls_id)

            caveats = [UNCALIBRATED_CAVEAT]
            if class_name == "chemical_pollution":
                caveats.append(CHEMICAL_CAVEAT)
            lat = lon = None
            geo_bbox = None

            if geo_bounds and img_w and img_h:
                geo_bbox = self._pixel_bbox_to_geo(xyxy, img_w, img_h, geo_bounds)
                lon = (geo_bbox[0] + geo_bbox[2]) / 2
                lat = (geo_bbox[1] + geo_bbox[3]) / 2
            else:
                caveats.append(UNGEOREFERENCED_CAVEAT)

            area_px = int(max(0.0, xyxy[2] - xyxy[0]) * max(0.0, xyxy[3] - xyxy[1]))

            detections.append(
                Detection(
                    signature=signature,
                    confidence=conf,
                    confidence_is_calibrated=False,
                    method=self.method,
                    model_version=self.version,
                    evidence_level=EvidenceLevel.DETECTED,
                    bbox=xyxy,
                    geo_bbox=geo_bbox,
                    latitude=lat,
                    longitude=lon,
                    area_pixels=area_px,
                    class_id=cls_id,
                    class_name=class_name,
                    caveats=caveats,
                    extra={"image_width": img_w, "image_height": img_h},
                )
            )

        return self._validate(detections)

    @staticmethod
    def _pixel_bbox_to_geo(
        bbox: list[float], img_w: int, img_h: int, bounds: list[float]
    ) -> list[float]:
        """Map a pixel bbox to WGS84 assuming a north-up linear image grid.

        This is only valid for an image whose bounds are a plain lat/lon
        rectangle. Reprojection for other CRSs belongs in the ingestion
        layer, which is why bounds are passed in rather than guessed.
        """
        min_lon, min_lat, max_lon, max_lat = bounds
        lon_span = max_lon - min_lon
        lat_span = max_lat - min_lat
        x1, y1, x2, y2 = bbox
        return [
            min_lon + (x1 / img_w) * lon_span,
            # Image y grows downward, latitude grows upward.
            max_lat - (y2 / img_h) * lat_span,
            min_lon + (x2 / img_w) * lon_span,
            max_lat - (y1 / img_h) * lat_span,
        ]
