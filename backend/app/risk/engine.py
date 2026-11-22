"""Deterministic environmental risk engine.

Design rules
------------
1. **The score is arithmetic, never an LLM output.** A language model may
   later *explain* a score; it may not produce one. A number a model invented
   cannot be audited, reproduced, or defended.
2. **Every point is attributable.** The engine returns a
   :class:`RiskContribution` per factor, and the contributions sum to the
   score. The dashboard's explanation panel renders exactly these numbers.
3. **Missing data is visible, not silently favourable.** If proximity data is
   unavailable, that factor is dropped and the score is renormalised over the
   factors that *were* evaluable, with the omission listed in
   ``missing_factors``. Treating unknown as zero would make an unmeasured
   event look safe, which is the more dangerous failure direction.

The weights below are a documented product judgement, not a physical
constant. They are versioned (:data:`ENGINE_VERSION`) so a stored assessment
can always be traced to the weighting that produced it.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from app.models.enums import EvidenceLevel, PollutionSignature, Severity
from app.risk.geo import GeographicDataProvider, get_geographic_provider

ENGINE_VERSION = "risk-engine-1.0.0"


@dataclass(slots=True)
class RiskContribution:
    """One factor's contribution to the total score."""

    factor: str
    points: float
    max_points: float
    detail: str
    evidence_level: str

    def to_dict(self) -> dict:
        """Serialise for the API and for storage in the assessment row."""
        return asdict(self)


@dataclass(slots=True)
class RiskResult:
    """Full, reproducible output of a risk evaluation."""

    score: float
    severity: Severity
    engine_version: str
    contributions: list[RiskContribution] = field(default_factory=list)
    missing_factors: list[str] = field(default_factory=list)
    evidence_level: EvidenceLevel = EvidenceLevel.INFERRED
    narrative: str = ""

    def to_dict(self) -> dict:
        """Serialise the full result, contributions included."""
        return {
            "score": round(self.score, 2),
            "severity": str(self.severity),
            "engine_version": self.engine_version,
            "contributions": [c.to_dict() for c in self.contributions],
            "missing_factors": self.missing_factors,
            "evidence_level": str(self.evidence_level),
            "narrative": self.narrative,
        }


#: Maximum points each factor may contribute before renormalisation.
FACTOR_WEIGHTS: dict[str, float] = {
    "signature_severity": 20.0,
    "detection_confidence": 15.0,
    "affected_area": 20.0,
    "coastal_proximity": 15.0,
    "protected_area_proximity": 15.0,
    "historical_trend": 15.0,
}

#: How much concern each signature warrants on its own. Ordered by how
#: directly the signature implies harm, and by how much the sensing modality
#: can actually support the claim.
SIGNATURE_SEVERITY: dict[str, float] = {
    PollutionSignature.OIL_LIKE_SIGNATURE: 1.00,
    PollutionSignature.ALGAE_BLOOM_SIGNATURE: 0.65,
    PollutionSignature.PLASTIC_DEBRIS_SIGNATURE: 0.55,
    # Floating material carries the same weight as the deprecated plastic
    # signature it replaces: the measurement is identical, only the claim is
    # narrower. Turbidity sits lowest of the optical signatures because on
    # this coast it is usually a river doing what rivers do.
    PollutionSignature.FLOATING_MATERIAL: 0.55,
    PollutionSignature.TURBIDITY_PLUME: 0.35,
    PollutionSignature.DARK_FORMATION: 0.45,
    PollutionSignature.SURFACE_ANOMALY: 0.30,
    PollutionSignature.NO_ANOMALY: 0.00,
}

#: Area (km^2) at which the area term saturates. Chosen so that a spill of
#: Deepwater-Horizon scale sits at the top of the range while ordinary
#: detections retain resolution in the lower decades.
AREA_SATURATION_KM2 = 500.0


class RiskEngine:
    """Computes an explainable 0-100 environmental risk score."""

    version = ENGINE_VERSION

    def __init__(self, geo_provider: GeographicDataProvider | None = None) -> None:
        """Accept an injected geographic provider, for testing and swapping."""
        self.geo = geo_provider or get_geographic_provider()

    def assess(
        self,
        *,
        signature: str,
        confidence: float,
        latitude: float | None = None,
        longitude: float | None = None,
        estimated_area_km2: float | None = None,
        trend_slope: float | None = None,
        evidence_level: EvidenceLevel = EvidenceLevel.INFERRED,
    ) -> RiskResult:
        """Score one pollution event.

        Args:
            signature: A :class:`PollutionSignature` value.
            confidence: Detector score in [0, 1].
            latitude: Event latitude; enables the proximity factors.
            longitude: Event longitude.
            estimated_area_km2: Affected area, when it could be estimated.
            trend_slope: Change in regional daily risk per day, from the
                temporal analytics layer. Positive means worsening.
            evidence_level: Propagated onto the result; a risk computed from
                simulated inputs stays ``SIMULATED``.

        Returns:
            A :class:`RiskResult` whose contributions sum to ``score``.
        """
        contributions: list[RiskContribution] = []
        missing: list[str] = []

        # -- 1. Signature severity -----------------------------------------
        sig_weight = SIGNATURE_SEVERITY.get(signature, 0.30)
        contributions.append(
            RiskContribution(
                factor="signature_severity",
                points=round(sig_weight * FACTOR_WEIGHTS["signature_severity"], 2),
                max_points=FACTOR_WEIGHTS["signature_severity"],
                detail=(
                    f"Signature '{signature}' carries an intrinsic concern "
                    f"weight of {sig_weight:.2f}."
                ),
                evidence_level=str(EvidenceLevel.DETECTED),
            )
        )

        # -- 2. Detection confidence ---------------------------------------
        conf = max(0.0, min(1.0, float(confidence)))
        contributions.append(
            RiskContribution(
                factor="detection_confidence",
                points=round(conf * FACTOR_WEIGHTS["detection_confidence"], 2),
                max_points=FACTOR_WEIGHTS["detection_confidence"],
                detail=f"Detector confidence {conf:.2f} (uncalibrated score).",
                evidence_level=str(EvidenceLevel.DETECTED),
            )
        )

        # -- 3. Affected area ----------------------------------------------
        if estimated_area_km2 is not None and estimated_area_km2 > 0:
            # Log scale: harm grows with extent but with diminishing returns,
            # and detections span several orders of magnitude.
            ratio = min(1.0, float(estimated_area_km2) / AREA_SATURATION_KM2)
            area_term = math.log1p(9 * ratio) / math.log(10)
            contributions.append(
                RiskContribution(
                    factor="affected_area",
                    points=round(area_term * FACTOR_WEIGHTS["affected_area"], 2),
                    max_points=FACTOR_WEIGHTS["affected_area"],
                    detail=(
                        f"Estimated area {estimated_area_km2:.1f} km2 "
                        f"(log-scaled, saturating at {AREA_SATURATION_KM2:.0f} km2)."
                    ),
                    evidence_level=str(EvidenceLevel.INFERRED),
                )
            )
        else:
            missing.append("affected_area")

        # -- 4 & 5. Proximity factors --------------------------------------
        if latitude is not None and longitude is not None:
            coast = self.geo.distance_to_coast(latitude, longitude)
            coast_term = self._proximity_term(coast.distance_km, near_km=50, far_km=500)
            contributions.append(
                RiskContribution(
                    factor="coastal_proximity",
                    points=round(coast_term * FACTOR_WEIGHTS["coastal_proximity"], 2),
                    max_points=FACTOR_WEIGHTS["coastal_proximity"],
                    detail=(
                        f"~{coast.distance_km:.0f} km from {coast.nearest_name}. "
                        f"{coast.precision_note}"
                    ),
                    evidence_level=str(EvidenceLevel.INFERRED),
                )
            )

            mpa = self.geo.nearest_protected_area(latitude, longitude)
            mpa_term = self._proximity_term(mpa.distance_km, near_km=100, far_km=1000)
            contributions.append(
                RiskContribution(
                    factor="protected_area_proximity",
                    points=round(
                        mpa_term * FACTOR_WEIGHTS["protected_area_proximity"], 2
                    ),
                    max_points=FACTOR_WEIGHTS["protected_area_proximity"],
                    detail=(
                        f"~{mpa.distance_km:.0f} km from {mpa.nearest_name}. "
                        f"{mpa.precision_note}"
                    ),
                    evidence_level=str(EvidenceLevel.INFERRED),
                )
            )
        else:
            missing.extend(["coastal_proximity", "protected_area_proximity"])

        # -- 6. Historical trend -------------------------------------------
        if trend_slope is not None:
            # Slope is in risk-points per day. +2/day over a week is a clear
            # deterioration; that maps to the top of the range.
            trend_term = max(0.0, min(1.0, (float(trend_slope) + 1.0) / 3.0))
            direction = (
                "worsening"
                if trend_slope > 0.2
                else "improving"
                if trend_slope < -0.2
                else "stable"
            )
            contributions.append(
                RiskContribution(
                    factor="historical_trend",
                    points=round(trend_term * FACTOR_WEIGHTS["historical_trend"], 2),
                    max_points=FACTOR_WEIGHTS["historical_trend"],
                    detail=(
                        f"Regional trend {trend_slope:+.2f} risk points/day "
                        f"({direction})."
                    ),
                    evidence_level=str(EvidenceLevel.OBSERVED),
                )
            )
        else:
            missing.append("historical_trend")

        # -- Renormalise over evaluable factors ----------------------------
        awarded = sum(c.points for c in contributions)
        available_max = sum(c.max_points for c in contributions)
        score = (awarded / available_max) * 100.0 if available_max > 0 else 0.0
        # Rounded here, at the single point of computation, so the stored
        # score, the API's score and the sum of the rounded contributions all
        # agree. Rounding later would let them drift apart, and a score a
        # consumer cannot reconstruct from the breakdown is not explainable.
        score = round(max(0.0, min(100.0, score)), 2)

        result = RiskResult(
            score=score,
            severity=Severity.from_score(score),
            engine_version=self.version,
            contributions=contributions,
            missing_factors=missing,
            evidence_level=evidence_level,
        )
        result.narrative = self.explain(result)
        return result

    @staticmethod
    def _proximity_term(distance_km: float, near_km: float, far_km: float) -> float:
        """Map a distance to [0, 1]: 1 at or inside ``near_km``, 0 beyond ``far_km``.

        Linear in log-distance between the two anchors, because the
        difference between 10 km and 50 km matters far more than the
        difference between 800 km and 840 km.
        """
        if distance_km <= near_km:
            return 1.0
        if distance_km >= far_km:
            return 0.0
        return 1.0 - (math.log(distance_km / near_km) / math.log(far_km / near_km))

    @staticmethod
    def explain(result: RiskResult) -> str:
        """Render a plain-text explanation from the contributions alone.

        Deliberately template-based. This text is derived from the same
        numbers the API returns, so the explanation cannot drift away from
        the score the way a generated summary can.
        """
        lines = [
            f"Risk score {result.score:.0f}/100 ({result.severity}), "
            f"computed by {result.engine_version}.",
            "",
            "Contributing factors:",
        ]
        for contrib in sorted(result.contributions, key=lambda c: c.points, reverse=True):
            lines.append(
                f"  {contrib.factor:<26} {contrib.points:>6.1f} / "
                f"{contrib.max_points:<5.0f}  {contrib.detail}"
            )
        if result.missing_factors:
            lines += [
                "",
                "Not evaluated (score renormalised over the remaining factors, "
                "so this is a partial assessment rather than a low one):",
                "  " + ", ".join(result.missing_factors),
            ]
        return "\n".join(lines)


_engine: RiskEngine | None = None


def get_risk_engine() -> RiskEngine:
    """Return the process-wide risk engine."""
    global _engine
    if _engine is None:
        _engine = RiskEngine()
    return _engine
