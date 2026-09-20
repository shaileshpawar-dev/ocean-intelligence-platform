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


# ---------------------------------------------------------------------------
# India Water Intelligence vocabularies
#
# These sit alongside the marine-pollution vocabularies above rather than
# replacing them. A satellite pollution detection and a laboratory BOD
# measurement are different kinds of claim, and collapsing them into one
# enum is exactly the conflation this platform exists to avoid.
# ---------------------------------------------------------------------------
class WaterBodyType(StrEnum):
    """What kind of water body a record describes.

    Kept explicit because behaviour genuinely differs: a river has stretches
    and an upstream/downstream order, a lake does not.
    """

    RIVER = "river"
    RIVER_STRETCH = "river_stretch"
    LAKE = "lake"
    POND = "pond"
    RESERVOIR = "reservoir"
    CANAL = "canal"
    CREEK = "creek"
    ESTUARY = "estuary"
    COASTAL = "coastal"
    MARINE = "marine"
    GROUNDWATER = "groundwater"
    DRAIN = "drain"
    OTHER = "other"
    """Used when the source gives no basis to classify. Never guessed."""


class WaterEvidenceType(StrEnum):
    """How a piece of water-body evidence came to exist.

    The separation that matters most is MEASURED from everything else. A
    laboratory BOD value and a satellite turbidity proxy are both useful and
    are not the same claim; only one of them is a measurement of the quantity
    it names.
    """

    MEASURED = "MEASURED"
    """Laboratory or field instrument measurement of the named quantity."""

    SATELLITE_OBSERVED = "SATELLITE_OBSERVED"
    """Derived from satellite reflectance or backscatter. A proxy, not a lab
    value. Never describes BOD, COD, coliform or dissolved metals."""

    IMAGE_DETECTED = "IMAGE_DETECTED"
    """Output of a detector run on an image. Describes appearance only."""

    REPORTED = "REPORTED"
    """Asserted by a document, bulletin or person. Not independently verified."""

    INFERRED = "INFERRED"
    """Derived by reasoning over other evidence. The weakest claim."""

    FORECAST = "FORECAST"
    """A projection about the future."""

    RETRIEVED = "RETRIEVED"
    """A passage retrieved from the document corpus, quoted as found."""


class WaterStatus(StrEnum):
    """Evidence-based status of a water body.

    Deliberately not a 0-100 score. A single number invites the reader to
    believe a precision the underlying monthly grab samples cannot support,
    and it hides which parameter drove it. Each band below is reached by a
    stated rule over named parameters against a cited standard.
    """

    WITHIN_REFERENCE = "WITHIN_REFERENCE"
    """Every evaluable parameter satisfies the selected standard."""

    ELEVATED = "ELEVATED"
    """At least one parameter breaches its limit, none severely."""

    HIGH_CONCERN = "HIGH_CONCERN"
    """Severe breach, or several simultaneous breaches."""

    POLLUTED_STRETCH = "POLLUTED_STRETCH"
    """Meets CPCB's national polluted-river-stretch criterion on BOD."""

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    """Observations exist but none of the parameters the standard needs."""

    NO_RECENT_DATA = "NO_RECENT_DATA"
    """Latest observation is too old to describe the present state."""


class QualityFlag(StrEnum):
    """Result of validating one ingested record.

    Malformed values are flagged and kept, not silently dropped. A discarded
    record is invisible; a flagged one can be counted, inspected and fixed.
    """

    OK = "ok"
    SUSPECT = "suspect"
    """Parsed, but a validation rule fired -- implausible magnitude, censored
    value, future date."""

    INVALID = "invalid"
    """Could not be parsed into the parameter's type at all."""
