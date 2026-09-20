"""The water status engine.

What it refuses to do
---------------------
It does not produce a 0-100 "pollution score". A single number would imply a
precision that monthly grab samples cannot support, it would hide which
parameter drove it, and -- worst -- it would let unmeasured parameters quietly
average away a real exceedance. Instead the engine returns a **band**, the
**named parameters** that put it there, and the **cited limit** each one
breached.

It also refuses to describe the present state of a water body from an
observation that is too old to support such a claim. That check runs first,
before any threshold comparison, because no amount of parameter analysis
makes a 2021 sample a statement about today.

How a band is reached
---------------------
1. If nothing was ever observed -> ``NO_RECENT_DATA`` with that stated.
2. If the latest observation is too old for its source's cadence ->
   ``NO_RECENT_DATA``, carrying the historical reading and its date.
3. If no parameter covered by the selected standard was measured ->
   ``INSUFFICIENT_DATA``. Emphatically not "clean".
4. If BOD exceeds the national polluted-stretch threshold ->
   ``POLLUTED_STRETCH``, with the CPCB priority band.
5. Else, by the breaches found: a severe breach or three or more breaches ->
   ``HIGH_CONCERN``; one or two -> ``ELEVATED``; none -> ``WITHIN_REFERENCE``.

Every branch is reported in ``reasons`` so the UI can answer "why this
status?" from the engine's own output rather than by re-deriving it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.enums import WaterStatus
from app.water.freshness import Cadence, FreshnessAssessment, assess
from app.water.parameters import BY_KEY
from app.water.standards import (
    DEFAULT_USE,
    USE_LABELS,
    Comparison,
    DesignatedUse,
    compare,
    priority_band,
    threshold_for,
)

ENGINE_VERSION = "water-status-1.0.0"

# A breach this far past its limit counts as severe on its own. Three times a
# regulatory limit is not a marginal exceedance under any reading.
SEVERE_EXCEEDANCE_FACTOR = 3.0

# Number of simultaneous breaches that escalates to HIGH_CONCERN without any
# single one being severe.
MULTI_BREACH_ESCALATION = 3

STATUS_LABELS: dict[WaterStatus, str] = {
    WaterStatus.WITHIN_REFERENCE: "Within reference",
    WaterStatus.ELEVATED: "Elevated",
    WaterStatus.HIGH_CONCERN: "High concern",
    WaterStatus.POLLUTED_STRETCH: "Polluted stretch",
    WaterStatus.INSUFFICIENT_DATA: "Insufficient data",
    WaterStatus.NO_RECENT_DATA: "No recent data",
}

# Ordering used when rolling several stations up to one water body. Worse
# outcomes win; the two "we do not know" bands rank below every real finding
# so a single measured breach is never masked by a silent neighbour.
_SEVERITY_ORDER: dict[WaterStatus, int] = {
    WaterStatus.NO_RECENT_DATA: 0,
    WaterStatus.INSUFFICIENT_DATA: 1,
    WaterStatus.WITHIN_REFERENCE: 2,
    WaterStatus.ELEVATED: 3,
    WaterStatus.HIGH_CONCERN: 4,
    WaterStatus.POLLUTED_STRETCH: 5,
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
class StatusResult:
    """A status band plus everything needed to defend it."""

    status: WaterStatus
    designated_use: DesignatedUse
    freshness: FreshnessAssessment
    comparisons: list[Comparison] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    priority: str | None = None
    priority_description: str | None = None
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
        """Serialise the verdict together with its justification."""
        return {
            "status": str(self.status),
            "label": self.label,
            "designated_use": str(self.designated_use),
            "designated_use_label": USE_LABELS[self.designated_use],
            "describes_present_state": self.freshness.describes_present_state,
            "freshness": self.freshness.to_dict(),
            "reasons": self.reasons,
            "priority_band": self.priority,
            "priority_description": self.priority_description,
            "evaluated_parameters": self.evaluated_parameters,
            "missing_parameters": self.missing_parameters,
            "failing_parameters": [c.to_dict() for c in self.failing],
            "comparisons": [c.to_dict() for c in self.comparisons],
            "engine_version": self.engine_version,
        }


def evaluate(
    measurements: list[Measurement],
    *,
    use: DesignatedUse = DEFAULT_USE,
    cadence: Cadence = Cadence.MONTHLY,
    now: datetime | None = None,
) -> StatusResult:
    """Classify a water body from its latest measurements.

    Only the most recent value per parameter is judged. Averaging across
    months would smear a spike that matters into a mean that does not, and
    the regulatory limits are written against individual samples.
    """
    if not measurements:
        freshness = assess(None, cadence, now=now)
        return StatusResult(
            status=WaterStatus.NO_RECENT_DATA,
            designated_use=use,
            freshness=freshness,
            reasons=[
                "No observation has ever been recorded for this water body. "
                "This is an absence of data, not evidence that the water is "
                "clean."
            ],
        )

    # Latest value per parameter.
    latest: dict[str, Measurement] = {}
    for m in measurements:
        held = latest.get(m.parameter_key)
        if held is None or m.observed_at > held.observed_at:
            latest[m.parameter_key] = m

    newest = max(m.observed_at for m in latest.values())
    freshness = assess(newest, cadence, now=now)

    # -- Gate 1: is this observation allowed to describe the present? ------
    if not freshness.describes_present_state:
        return StatusResult(
            status=WaterStatus.NO_RECENT_DATA,
            designated_use=use,
            freshness=freshness,
            reasons=[
                freshness.summary(),
                "No present-tense status is derived from an observation this "
                "old. The historical measurements remain available, dated.",
            ],
        )

    # -- Gate 2: did anyone measure what the standard actually governs? ----
    comparisons: list[Comparison] = []
    missing: list[str] = []
    for key, measurement in sorted(latest.items()):
        param = BY_KEY.get(key)
        if param is None:
            continue
        if threshold_for(key, use) is None:
            continue
        comparisons.append(compare(param, measurement.value, use))

    for key in sorted(_standard_keys(use)):
        if key not in latest:
            param = BY_KEY.get(key)
            missing.append(param.label if param else key)

    evaluable = [
        c
        for c in comparisons
        if c.compliance.value not in ("not_measured", "no_standard")
    ]

    if not evaluable:
        return StatusResult(
            status=WaterStatus.INSUFFICIENT_DATA,
            designated_use=use,
            freshness=freshness,
            comparisons=comparisons,
            missing_parameters=missing,
            reasons=[
                f"Observations exist, but none of the parameters that class "
                f"{use} governs were measured. Status cannot be determined; "
                "this is not a finding that the water is within limits.",
                freshness.summary(),
            ],
        )

    failing = [c for c in evaluable if c.failed]
    reasons = [c.explain() for c in failing] or [
        f"All {len(evaluable)} evaluable parameter(s) satisfy the class {use} limits."
    ]
    reasons.append(freshness.summary())
    if missing:
        reasons.append("Not evaluated (not measured): " + ", ".join(missing) + ".")

    # -- Gate 3: the national polluted-stretch criterion -------------------
    bod = latest.get("bod")
    band = priority_band(bod.value) if bod else None
    if band is not None:
        priority, description = band
        return StatusResult(
            status=WaterStatus.POLLUTED_STRETCH,
            designated_use=use,
            freshness=freshness,
            comparisons=comparisons,
            reasons=[
                f"Biochemical oxygen demand is {bod.value} mg/L, above the "
                "3 mg/L threshold CPCB uses nationally to identify a polluted "
                f"location (restoration priority {priority}: {description}).",
                *reasons,
            ],
            priority=priority,
            priority_description=description,
            evaluated_parameters=len(evaluable),
            missing_parameters=missing,
        )

    # -- Gate 4: severity from the breaches found --------------------------
    severe = [
        c
        for c in failing
        if c.exceedance_factor is not None
        and c.exceedance_factor >= SEVERE_EXCEEDANCE_FACTOR
    ]

    if severe or len(failing) >= MULTI_BREACH_ESCALATION:
        status = WaterStatus.HIGH_CONCERN
        if severe:
            reasons.insert(
                0,
                f"{severe[0].parameter_label} is at least "
                f"{SEVERE_EXCEEDANCE_FACTOR:g} times its class {use} limit.",
            )
        else:
            reasons.insert(
                0,
                f"{len(failing)} parameters simultaneously breach their "
                f"class {use} limits.",
            )
    elif failing:
        status = WaterStatus.ELEVATED
    else:
        status = WaterStatus.WITHIN_REFERENCE

    return StatusResult(
        status=status,
        designated_use=use,
        freshness=freshness,
        comparisons=comparisons,
        reasons=reasons,
        evaluated_parameters=len(evaluable),
        missing_parameters=missing,
    )


def _standard_keys(use: DesignatedUse) -> set[str]:
    """Parameter keys the selected standard sets a limit for."""
    from app.water.standards import thresholds_for_use

    return {t.parameter_key for t in thresholds_for_use(use)}


def roll_up(results: list[StatusResult]) -> WaterStatus:
    """Combine per-station statuses into one for a water body.

    Takes the worst real finding. A river with one clean station and one
    polluted station is not half-clean: the pollution is the fact that
    matters, and averaging it away would be the single most misleading thing
    this platform could do.
    """
    if not results:
        return WaterStatus.NO_RECENT_DATA
    return max((r.status for r in results), key=lambda s: _SEVERITY_ORDER[s])


def status_rank(status: WaterStatus) -> int:
    """Severity rank, exposed so the API can sort without re-deriving it."""
    return _SEVERITY_ORDER[status]
