"""Controlled vocabularies shared by the database, schemas and services.

The distinctions encoded here are the heart of the platform's scientific
honesty requirement: a *measurement* is not a *detection*, and a *detection*
is not a *confirmed pollution event*.
"""

from __future__ import annotations

from enum import StrEnum


class EvidenceLevel(StrEnum):
    """How a value came to exist. Every payload the API returns carries one.

    This is what keeps the platform honest. A dark patch measured by
    Sentinel-1 is ``OBSERVED``; the claim that it is a surface film is
    ``DETECTED``; the claim that it came from a passing vessel is
    ``INFERRED``; next week's risk is ``FORECAST``; demo-mode fixtures are
    ``SIMULATED``.
    """

    OBSERVED = "OBSERVED"
    """Directly measured from sensor data (e.g. mean VV backscatter in dB)."""

    DETECTED = "DETECTED"
    """Output of a detector applied to observed data. Carries uncertainty."""

    INFERRED = "INFERRED"
    """Derived by reasoning over detections plus context. Weakest claim."""

    FORECAST = "FORECAST"
    """A projection about the future. Never presented as fact."""

    SIMULATED = "SIMULATED"
    """Synthetic data generated for demo or test purposes. Never real."""


class PollutionSignature(StrEnum):
    """What the sensing modality can actually support as a claim.

    Deliberately *not* a list of pollutant types. C-band SAR (Sentinel-1 VV)
    measures surface roughness. It can identify a region of anomalously low
    backscatter -- a "dark formation" -- which is the standard first-pass
    indicator for a surface film. It cannot tell oil from a biogenic slick,
    a low-wind cell, or rain cell attenuation, and it certainly cannot
    identify plastic or dissolved chemicals.

    Optical instruments (Sentinel-2) support a different, partly overlapping
    set of claims. The signature therefore records what was seen, and
    ``detection_method`` records how -- so a consumer can judge the claim.
    """

    OIL_LIKE_SIGNATURE = "oil_like_signature"
    """Dark formation whose shape/contrast is consistent with a surface film."""

    DARK_FORMATION = "dark_formation"
    """Low-backscatter anomaly, cause undetermined. Includes look-alikes."""

    ALGAE_BLOOM_SIGNATURE = "algae_bloom_signature"
    """Optical-only. Elevated chlorophyll-a / discolouration."""

    PLASTIC_DEBRIS_SIGNATURE = "plastic_debris_signature"
    """Optical-only, high uncertainty. Floating debris-like reflectance."""

    SURFACE_ANOMALY = "surface_anomaly"
    """Anomalous but unclassifiable under the available modality."""

    NO_ANOMALY = "no_anomaly"
    """Measured and found unremarkable. An explicit negative is data too."""


class DetectionMethod(StrEnum):
    """How a detection was produced. Determines how much it can support."""

    SAR_DARK_FORMATION = "sar_dark_formation"
    """Threshold + contrast analysis on Sentinel-1 VV backscatter."""

    YOLO_OPTICAL = "yolo_optical"
    """YOLO object detector run on an optical/RGB image."""

    MANUAL = "manual"
    """Human-entered."""

    SIMULATED = "simulated"
    """Demo-mode fixture."""


class Severity(StrEnum):
    """Ordinal severity band derived from the deterministic risk engine."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_score(cls, score: float) -> Severity:
        """Map a 0-100 risk score onto a band.

        Thresholds are a product decision, documented in docs/evaluation.md,
        not a scientific constant.
        """
        if score >= 75:
            return cls.CRITICAL
        if score >= 50:
            return cls.HIGH
        if score >= 25:
            return cls.MEDIUM
        return cls.LOW


class ModelStatus(StrEnum):
    """Lifecycle stage of a registered model version."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class DriftStatus(StrEnum):
    """Outcome of a drift check."""

    OK = "ok"
    WARNING = "warning"
    DRIFT_DETECTED = "drift_detected"
    INSUFFICIENT_DATA = "insufficient_data"


class AgentRunStatus(StrEnum):
    """Terminal state of an agent workflow run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
