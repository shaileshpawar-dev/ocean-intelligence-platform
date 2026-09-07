"""Dark-formation detection on Sentinel-1 C-band VV backscatter.

Why this module exists
----------------------
The system this replaces assigned pollution *classes* by rank-ordering ocean
cells by mean backscatter and slicing the sorted list into five equal buckets.
That guarantees a fixed number of "oil spills" regardless of what is in the
water, and it claims class distinctions (plastic, chemical) that C-band SAR
physically cannot make.

What SAR can actually support
-----------------------------
A surface film damps short gravity-capillary waves, reducing Bragg scattering
and producing a region of anomalously **low** backscatter -- a *dark
formation*. Dark-formation detection is the accepted first stage of every
operational SAR oil-spill pipeline (e.g. CleanSeaNet). The second stage,
discriminating true slicks from look-alikes, needs feature analysis on the
full-resolution scene and, in practice, wind data.

This detector implements stage one honestly, on the regional statistics the
ingestion layer already computes, and attaches the look-alike caveats
explicitly rather than hiding them behind a confident-looking number.

Known look-alikes (all reported as caveats, never silently ignored):
  * low-wind cells (below ~3 m/s the sea surface is intrinsically dark)
  * biogenic slicks from algal exudates
  * rain cell damping and wind shadows near coastlines
  * grease ice at high latitude
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature
from app.vision.base import BaseDetector, Detection

logger = get_logger(__name__)

#: Minimum p90-p10 spread (dB) for a cell to be considered *structured*
#: rather than uniformly dark. A real slick is a dark patch inside a
#: normally-scattering sea; a low-wind cell is dark everywhere.
MIN_CONTRAST_DB = 3.0

#: Contrast (dB) at which the contrast term saturates.
CONTRAST_SATURATION_DB = 12.0

#: Depth below the dark threshold (dB) at which the depth term saturates.
DEPTH_SATURATION_DB = 8.0

#: A heuristic score is never allowed to present as near-certainty.
MAX_HEURISTIC_CONFIDENCE = 0.85
MIN_REPORTED_CONFIDENCE = 0.30

#: Upper bound (km^2) on a physically plausible surface slick. For scale,
#: Deepwater Horizon peaked in the low thousands of km^2 and was among the
#: largest marine spills on record. A contiguous dark region an order of
#: magnitude beyond that is a met-ocean feature -- a low-wind zone, a
#: rain-cell footprint, an atmospheric front -- not a slick. Detections above
#: this are downgraded from an oil-like claim to a bare dark formation.
MAX_PLAUSIBLE_SLICK_KM2 = 5_000.0

RESOLUTION_CAVEAT = (
    "This detector screens whole monitoring cells (typically 10^4-10^5 km^2) "
    "using aggregate statistics. It localises which cell warrants attention; "
    "it does not delineate a slick. Confirming and measuring a feature "
    "requires full-resolution analysis of the source scene."
)
IMPLAUSIBLE_EXTENT_CAVEAT = (
    "The low-backscatter region spans more than "
    f"{MAX_PLAUSIBLE_SLICK_KM2:,.0f} km^2, which exceeds any recorded marine "
    "oil slick by a wide margin. A dark area at this scale is characteristic "
    "of a met-ocean phenomenon (low-wind zone, rain cell, atmospheric front). "
    "Downgraded to an unclassified dark formation."
)

LOOKALIKE_CAVEAT = (
    "Dark formations in C-band VV are not unique to oil. Low wind (<3 m/s), "
    "biogenic slicks, rain cells and wind shadows produce the same signature. "
    "Confirmation requires wind data and full-resolution scene analysis."
)
UNCALIBRATED_CAVEAT = (
    "Confidence is a heuristic score derived from backscatter contrast, not a "
    "calibrated probability. It has not been validated against labelled spills."
)
COARSE_AREA_CAVEAT = (
    "Area is interpolated from regional percentile statistics, not measured "
    "from a segmentation mask. Treat it as an order-of-magnitude estimate."
)


def estimate_dark_fraction(p10_db: float, p90_db: float, threshold_db: float) -> float:
    """Estimate the fraction of a cell darker than ``threshold_db``.

    Only the 10th and 90th percentiles are available from the ingestion
    reducer, so this linearly interpolates the implied distribution between
    those two anchors. It is deliberately coarse and is reported as such via
    :data:`COARSE_AREA_CAVEAT`; a segmentation mask replaces it once one is
    available (see :mod:`app.vision.segmentation`).

    Returns:
        A fraction in [0, 1].
    """
    if p90_db <= p10_db:
        return 1.0 if p10_db < threshold_db else 0.0
    if threshold_db <= p10_db:
        # Even the 10th percentile is above the threshold's darkness, so at
        # most the bottom decile qualifies.
        return 0.10
    if threshold_db >= p90_db:
        return 1.0
    # Fraction of the p10..p90 span (which covers 80% of pixels) that lies
    # below the threshold, plus the bottom decile which is darker than p10.
    span_fraction = (threshold_db - p10_db) / (p90_db - p10_db)
    return max(0.0, min(1.0, 0.10 + 0.80 * span_fraction))


class SARDarkFormationDetector(BaseDetector):
    """Stage-one dark-formation detector over regional SAR statistics.

    The detector consumes the statistics produced by the ingestion layer
    (mean / p10 / p90 / stddev of VV in dB) rather than raw pixels, because
    those are what the Earth Engine reducer returns for a monitoring cell.
    It emits at most one detection per cell.
    """

    name = "sar-dark-formation"
    version = "1.0.0"
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
        threshold_db: float | None = None,
        min_contrast_db: float = MIN_CONTRAST_DB,
    ) -> None:
        """Set the darkness threshold and the minimum structure contrast."""
        self.threshold_db = (
            threshold_db if threshold_db is not None else settings.sar_dark_threshold_db
        )
        self.min_contrast_db = min_contrast_db

    def predict(self, payload: Any, **kwargs: Any) -> list[Detection]:
        """Analyse one cell's backscatter statistics.

        Args:
            **kwargs: Unused; present for interface compatibility.
            payload: Mapping with ``mean_db``, ``p10_db``, ``p90_db`` and
                optionally ``stddev_db``, ``area_km2``, ``latitude``,
                ``longitude``, ``wind_speed_ms``.

        Returns:
            A single-element list, or an empty list when the input lacks the
            statistics needed to make any claim at all.
        """
        stats = dict(payload)
        p10 = stats.get("p10_db")
        p90 = stats.get("p90_db")
        mean = stats.get("mean_db")

        if p10 is None or p90 is None or mean is None:
            logger.warning(
                "sar_detector_insufficient_stats",
                extra={"cell": stats.get("region_code")},
            )
            return []

        contrast_db = float(p90) - float(p10)
        lat = stats.get("latitude")
        lon = stats.get("longitude")
        cell_area_km2 = stats.get("area_km2")
        wind = stats.get("wind_speed_ms")

        base_extra = {
            "mean_db": round(float(mean), 2),
            "p10_db": round(float(p10), 2),
            "p90_db": round(float(p90), 2),
            "contrast_db": round(contrast_db, 2),
            "threshold_db": self.threshold_db,
        }

        # -- No dark pixels at all: an explicit, useful negative result -----
        if float(p10) >= self.threshold_db:
            return self._validate(
                [
                    Detection(
                        signature=PollutionSignature.NO_ANOMALY,
                        confidence=1.0 - self._normalised_depth(float(p10)),
                        confidence_is_calibrated=False,
                        method=self.method,
                        model_version=self.version,
                        evidence_level=EvidenceLevel.DETECTED,
                        latitude=lat,
                        longitude=lon,
                        caveats=[UNCALIBRATED_CAVEAT],
                        extra=base_extra,
                    )
                ]
            )

        depth_term = self._normalised_depth(float(p10))
        contrast_term = max(
            0.0,
            min(
                1.0,
                (contrast_db - self.min_contrast_db)
                / (CONTRAST_SATURATION_DB - self.min_contrast_db),
            ),
        )

        caveats = [LOOKALIKE_CAVEAT, UNCALIBRATED_CAVEAT]

        # -- Uniformly dark cell: most likely a low-wind look-alike --------
        if contrast_db < self.min_contrast_db:
            signature = PollutionSignature.DARK_FORMATION
            # Structure is what distinguishes a slick; without it, stay low.
            score = 0.20 + 0.30 * depth_term
            caveats.insert(
                0,
                "Cell is uniformly dark (p90-p10 = "
                f"{contrast_db:.1f} dB < {self.min_contrast_db} dB). Uniform "
                "darkness is more consistent with a low-wind sea state than "
                "with a localised surface film.",
            )
        else:
            signature = PollutionSignature.OIL_LIKE_SIGNATURE
            score = 0.5 * depth_term + 0.5 * contrast_term

        # Wind, when available, is the single most informative disambiguator.
        if wind is not None:
            base_extra["wind_speed_ms"] = wind
            if float(wind) < settings.sar_min_wind_speed_ms:
                score *= 0.5
                caveats.insert(
                    0,
                    f"Measured wind speed {float(wind):.1f} m/s is below "
                    f"{settings.sar_min_wind_speed_ms} m/s; dark formations "
                    "are not separable from the low-wind background here.",
                )
            elif float(wind) > 10.0:
                # High wind roughens the sea, so a persistent dark patch is
                # harder to explain away as a look-alike.
                score = min(1.0, score * 1.15)
                caveats.append(
                    f"Wind speed {float(wind):.1f} m/s is high enough that a "
                    "low-wind look-alike is unlikely."
                )

        confidence = max(
            MIN_REPORTED_CONFIDENCE,
            min(MAX_HEURISTIC_CONFIDENCE, MIN_REPORTED_CONFIDENCE + score * 0.55),
        )

        # -- Coarse extent estimate ----------------------------------------
        area_km2 = None
        area_method = None
        dark_fraction = estimate_dark_fraction(float(p10), float(p90), self.threshold_db)
        base_extra["dark_fraction_estimate"] = round(dark_fraction, 3)
        if cell_area_km2:
            area_km2 = round(float(cell_area_km2) * dark_fraction, 2)
            area_method = "percentile_interpolation_coarse"
            caveats.append(COARSE_AREA_CAVEAT)

        # -- Physical plausibility gate ------------------------------------
        # A dark region far larger than any recorded slick cannot be a slick.
        # Downgrading here, rather than downstream, keeps the implausible
        # claim from ever entering the database or a report.
        if (
            area_km2 is not None
            and area_km2 > MAX_PLAUSIBLE_SLICK_KM2
            and signature == PollutionSignature.OIL_LIKE_SIGNATURE
        ):
            signature = PollutionSignature.DARK_FORMATION
            confidence_scale = 0.4
            caveats.insert(0, IMPLAUSIBLE_EXTENT_CAVEAT)
            base_extra["downgraded_from"] = str(PollutionSignature.OIL_LIKE_SIGNATURE)
            base_extra["downgrade_reason"] = "implausible_extent"
        else:
            confidence_scale = 1.0

        confidence *= confidence_scale
        confidence = max(MIN_REPORTED_CONFIDENCE, confidence)
        caveats.append(RESOLUTION_CAVEAT)

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
                    geo_bbox=stats.get("bbox"),
                    estimated_area_km2=area_km2,
                    area_method=area_method,
                    class_name=str(signature),
                    caveats=caveats,
                    extra=base_extra,
                )
            ]
        )

    def _normalised_depth(self, p10_db: float) -> float:
        """How far below the dark threshold the 10th percentile sits, in [0, 1]."""
        return max(0.0, min(1.0, (self.threshold_db - p10_db) / DEPTH_SATURATION_DB))
