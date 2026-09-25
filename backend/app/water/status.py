"""The water status engine.

Four layers, kept separate all the way to the API
---------------------------------------------------
A. **MEASURED** -- the values, as sampled, with their dates.
B. **REFERENCE_COMPARISON** -- each value judged against the reference
   standard that applies to this water body (see ``standards.select_reference``),
   or an explicit "no applicable reference".
C. **SOURCE_CLASSIFICATION** -- official classifications published by a
   source, such as CPCB's polluted-river-stretch list. Never manufactured
   from observations.
D. **DERIVED_STATUS** -- the band the platform reads from A-C, with every
   contributing parameter, limit, date and classification listed.

What it refuses to do
---------------------
No 0-100 score. No present-tense status from an observation too old to
support one. No comparison against a standard that nobody established applies.
No "polluted stretch" label unless a source published one.

How the band is reached
-----------------------
1. Nothing observed -> ``NO_RECENT_DATA``.
2. Latest observation too old for the source's cadence -> ``NO_RECENT_DATA``.
3. An official polluted-stretch classification -> ``POLLUTED_STRETCH``.
4. No applicable reference -> ``NO_APPLICABLE_REFERENCE``.
5. None of the governed parameters measured -> ``INSUFFICIENT_DATA``.
6. A breach at >=3x its limit, or three or more breaches -> ``HIGH_CONCERN``;
   one or two -> ``ELEVATED``; none -> ``WITHIN_REFERENCE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.enums import WaterStatus
from app.water.freshness import Cadence, FreshnessAssessment, assess
from app.water.parameters import BY_KEY
from app.water.standards import (
    Comparison,
    ReferenceSelection,
    SelectionBasis,
    compare,
    governed_parameters,
)

ENGINE_VERSION = "water-status-2.0.0"

SEVERE_EXCEEDANCE_FACTOR = 3.0
MULTI_BREACH_ESCALATION = 3

STATUS_LABELS: dict[WaterStatus, str] = {
    WaterStatus.WITHIN_REFERENCE: "Within reference",
    WaterStatus.ELEVATED: "Elevated",
    WaterStatus.HIGH_CONCERN: "High concern",
    WaterStatus.POLLUTED_STRETCH: "Polluted stretch",
    WaterStatus.INSUFFICIENT_DATA: "Insufficient data",
    WaterStatus.NO_RECENT_DATA: "No recent data",
    WaterStatus.NO_APPLICABLE_REFERENCE: "No applicable reference",
}

# Worse outcomes win a roll-up; the "we do not know" bands rank below every
# real finding so a silent station never masks a measured breach.
_SEVERITY_ORDER: dict[WaterStatus, int] = {
    WaterStatus.NO_RECENT_DATA: 0,
    WaterStatus.NO_APPLICABLE_REFERENCE: 1,
    WaterStatus.INSUFFICIENT_DATA: 2,
    WaterStatus.WITHIN_REFERENCE: 3,
    WaterStatus.ELEVATED: 4,
    WaterStatus.HIGH_CONCERN: 5,
    WaterStatus.POLLUTED_STRETCH: 6,
}


@dataclass(slots=True)
class Measurement:
    """One parameter value carried into the engine."""

    parameter_key: str
    value: float | None
    observed_at: datetime
    unit: str | None = None
    station_id: int | None = None
    station_name: str | None = None
    source: str | None = None


@dataclass(slots=True)
class ClassificationRef:
    """An official classification, carried into the engine as-is."""

    source: str
    classification_type: str
    assessment_year: int | None
    priority: str | None
    stretch_name: str | None
    source_reference: str

    def to_dict(self) -> dict:
        """Serialise as a SOURCE_CLASSIFICATION evidence item."""
        return {
            "evidence_type": "SOURCE_CLASSIFICATION",
            "source": self.source,
            "classification_type": self.classification_type,
            "assessment_year": self.assessment_year,
            "priority": self.priority,
            "stretch_name": self.stretch_name,
            "source_reference": self.source_reference,
        }


@dataclass(slots=True)
class StatusResult:
    """The four layers plus everything needed to defend the band."""

    status: WaterStatus
    reference: ReferenceSelection
    freshness: FreshnessAssessment
    measurements: list[Measurement] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    classifications: list[ClassificationRef] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION
    evaluated_parameters: int = 0
    missing_parameters: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Display label for the band."""
        return STATUS_LABELS[self.status]

    @property
    def failing(self) -> list[Comparison]:
        """Only the genuine, measured breaches."""
        return [c for c in self.comparisons if c.failed]

    def to_dict(self) -> dict:
        """Serialise the layers separately, then the derived band."""
        standard = self.reference.standard
        return {
            # D. derived status
            "status": str(self.status),
            "label": self.label,
            "evidence_type": "DERIVED_STATUS",
            "reasons": self.reasons,
            "limitations": self.limitations,
            "describes_present_state": self.freshness.describes_present_state,
            "freshness": self.freshness.to_dict(),
            # A. measurements
            "measurements": [
                {
                    "parameter": m.parameter_key,
                    "label": BY_KEY[m.parameter_key].label
                    if m.parameter_key in BY_KEY
                    else m.parameter_key,
                    "value": m.value,
                    "unit": m.unit,
                    "observed_at": m.observed_at.isoformat(),
                    "source": m.source,
                    "evidence_type": "MEASURED",
                }
                for m in self.measurements
            ],
            # B. reference comparison
            "reference": self.reference.to_dict(),
            "comparisons": [c.to_dict() for c in self.comparisons],
            "failing_parameters": [c.to_dict() for c in self.failing],
            "evaluated_parameters": self.evaluated_parameters,
            "missing_parameters": self.missing_parameters,
            # C. source classification
            "source_classifications": [c.to_dict() for c in self.classifications],
            "engine_version": self.engine_version,
            # Kept for clients built against Phase 1.
            "designated_use": standard.code if standard else None,
            "designated_use_label": standard.name
            if standard
            else "No applicable reference",
            "priority_band": next(
                (c.priority for c in self.classifications if c.priority), None
            ),
            "priority_description": None,
        }


def evaluate(
    measurements: list[Measurement],
    *,
    reference: ReferenceSelection,
    classifications: list[ClassificationRef] | None = None,
    cadence: Cadence = Cadence.MONTHLY,
    now: datetime | None = None,
) -> StatusResult:
    """Classify a water body from its latest measurement of each parameter.

    Only the most recent value per parameter is judged: limits are written
    against individual samples, and averaging months would smear real spikes.
    """
    classifications = classifications or []

    latest: dict[str, Measurement] = {}
    for m in measurements:
        held = latest.get(m.parameter_key)
        if held is None or m.observed_at > held.observed_at:
            latest[m.parameter_key] = m
    current = sorted(latest.values(), key=lambda m: m.parameter_key)

    newest = max((m.observed_at for m in current), default=None)
    freshness = assess(newest, cadence, now=now)

    result = StatusResult(
        status=WaterStatus.NO_RECENT_DATA,
        reference=reference,
        freshness=freshness,
        measurements=current,
        classifications=classifications,
    )

    if not current:
        result.reasons = [
            "No observation has ever been recorded for this water body. This is "
            "an absence of data, not evidence that the water is clean."
        ]
        return result

    # B. comparisons are computed whatever the freshness, so a reader can see
    # what the last sample showed; only the *present-tense* band is gated.
    governed = governed_parameters(reference.standard) if reference.standard else set()
    result.comparisons = [
        compare(m.parameter_key, m.value, reference.standard)
        for m in current
        if m.parameter_key in BY_KEY
        and (not reference.standard or m.parameter_key in governed)
    ]
    evaluable = [
        c
        for c in result.comparisons
        if c.compliance.value in ("within", "exceeds", "below")
    ]
    result.evaluated_parameters = len(evaluable)
    result.missing_parameters = sorted(
        BY_KEY[k].label for k in governed - set(latest) if k in BY_KEY
    )

    dates = sorted({m.observed_at.date() for m in current})
    date_note = (
        f"Observations used: {dates[0]:%d %b %Y}"
        if len(dates) == 1
        else f"Observations used: {dates[0]:%d %b %Y} to {dates[-1]:%d %b %Y}"
    )

    # 1-2. freshness gate
    if not freshness.describes_present_state:
        result.status = WaterStatus.NO_RECENT_DATA
        result.reasons = [
            freshness.summary(),
            "The current condition cannot be established from this dataset. The "
            "latest measurements remain available, dated.",
        ]
        return result

    # 3. official classification
    stretch = next(
        (c for c in classifications if c.classification_type == "polluted_river_stretch"),
        None,
    )
    if stretch is not None:
        result.status = WaterStatus.POLLUTED_STRETCH
        result.reasons = [
            f"{stretch.source} lists this water body"
            + (f" ({stretch.stretch_name})" if stretch.stretch_name else "")
            + " as a polluted river stretch"
            + (f", priority {stretch.priority}" if stretch.priority else "")
            + (
                f", assessment {stretch.assessment_year}"
                if stretch.assessment_year
                else ""
            )
            + ".",
            *(c.explain() for c in result.failing),
            date_note,
        ]
        return result

    # 4. no reference
    if not reference.available:
        result.status = WaterStatus.NO_APPLICABLE_REFERENCE
        result.reasons = [
            "Reference comparison unavailable. " + reference.reason,
            "The measured values are shown as measured; no judgement is made.",
            date_note,
        ]
        return result

    # 5. nothing governed was measured
    if not evaluable:
        result.status = WaterStatus.INSUFFICIENT_DATA
        result.reasons = [
            f"None of the parameters {reference.standard.name} governs was measured. "
            "Status cannot be determined; this is not a finding that the water is "
            "within limits.",
            date_note,
        ]
        return result

    # 6. severity from breaches
    failing = result.failing
    severe = [
        c
        for c in failing
        if c.exceedance_factor is not None
        and c.exceedance_factor >= SEVERE_EXCEEDANCE_FACTOR
    ]
    reasons = [c.explain() for c in failing] or [
        f"All {len(evaluable)} evaluated parameter(s) are within "
        f"{reference.standard.name}."
    ]
    if severe:
        result.status = WaterStatus.HIGH_CONCERN
        reasons.insert(
            0,
            f"{severe[0].parameter_label} is at least {SEVERE_EXCEEDANCE_FACTOR:g} "
            "times its limit.",
        )
    elif len(failing) >= MULTI_BREACH_ESCALATION:
        result.status = WaterStatus.HIGH_CONCERN
        reasons.insert(0, f"{len(failing)} parameters breach their limits at once.")
    elif failing:
        result.status = WaterStatus.ELEVATED
    else:
        result.status = WaterStatus.WITHIN_REFERENCE

    reasons.append(date_note)
    if result.missing_parameters:
        result.limitations.append(
            "Not evaluated because not measured: "
            + ", ".join(result.missing_parameters)
            + "."
        )
    if reference.basis is SelectionBasis.NATIONAL_ASSESSMENT_CATEGORY:
        result.limitations.append(
            "Reference chosen by CPCB's national assessment practice for rivers, "
            "not from a designated use recorded for this river."
        )
    result.reasons = reasons
    return result


def roll_up(results: list[StatusResult]) -> WaterStatus:
    """Combine per-station statuses: the worst real finding wins."""
    if not results:
        return WaterStatus.NO_RECENT_DATA
    return max((r.status for r in results), key=lambda s: _SEVERITY_ORDER[s])


def status_rank(status: WaterStatus) -> int:
    """Severity rank, exposed so the API can sort without re-deriving it."""
    return _SEVERITY_ORDER[status]
