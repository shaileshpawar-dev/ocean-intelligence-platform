"""Reference water-quality standards, with provenance on every threshold.

Why this module is not a dict of magic numbers
----------------------------------------------
"Is this river polluted?" has no answer until someone says *polluted for
what*. Water that is unfit to drink untreated may be perfectly fit for
irrigation. CPCB encodes exactly that idea in its **Designated Best Use**
classification: five classes, A through E, each with its own limits.

So a threshold here is never bare. It carries the use class it belongs to,
the organisation that set it, the document it came from and that document's
URL, and those travel with the comparison all the way into the API response.
A user who disagrees with a classification can see precisely which limit,
from which standard, produced it.

Sources
-------
* CPCB, *Designated Best Use Water Quality Criteria* (primary water quality
  criteria for the five classes).
* CPCB, *Polluted River Stretches in India: Criteria and Status* -- the BOD
  bands used nationally to prioritise river stretches for restoration.

Both are Indian national standards. No threshold in this module was invented
by the platform, and none is applied to a parameter the standard does not
cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.water.parameters import BY_KEY, Parameter


class DesignatedUse(StrEnum):
    """CPCB Designated-Best-Use classes for inland surface water."""

    A = "A"
    """Drinking water source without conventional treatment, after disinfection."""

    B = "B"
    """Outdoor bathing (organised)."""

    C = "C"
    """Drinking water source after conventional treatment and disinfection."""

    D = "D"
    """Propagation of wildlife and fisheries."""

    E = "E"
    """Irrigation, industrial cooling, controlled waste disposal."""


USE_LABELS: dict[DesignatedUse, str] = {
    DesignatedUse.A: "Drinking water source (disinfection only)",
    DesignatedUse.B: "Outdoor bathing (organised)",
    DesignatedUse.C: "Drinking water source (conventional treatment)",
    DesignatedUse.D: "Wildlife and fisheries",
    DesignatedUse.E: "Irrigation and industrial cooling",
}

CPCB_CRITERIA_SOURCE = "CPCB — Designated Best Use Water Quality Criteria"
CPCB_CRITERIA_URL = (
    "https://cpcb.nic.in/wqm/Designated_Best_Use_Water_Quality_Criteria.pdf"
)
CPCB_PRS_SOURCE = "CPCB — Polluted River Stretches in India: Criteria and Status"
CPCB_PRS_URL = "https://cpcb.nic.in/wqm/RS-criteria-status.pdf"

# Class C is the working default. It is the criterion for a drinking-water
# source with conventional treatment, which is what most monitored Indian
# river stretches are actually used for, and it is the class whose BOD limit
# (3 mg/L) coincides with the national polluted-stretch threshold. Any class
# can be selected per request; this is only the default.
DEFAULT_USE = DesignatedUse.C


@dataclass(frozen=True, slots=True)
class Threshold:
    """One limit for one parameter under one designated use."""

    parameter_key: str
    use: DesignatedUse
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    source: str = CPCB_CRITERIA_SOURCE
    source_url: str = CPCB_CRITERIA_URL
    note: str = ""

    def describe(self) -> str:
        """Render the limit in words, for the UI and reports."""
        param = BY_KEY.get(self.parameter_key)
        label = param.label if param else self.parameter_key
        unit = f" {self.unit}" if self.unit else ""
        if self.minimum is not None and self.maximum is not None:
            return f"{label} must be between {self.minimum} and {self.maximum}{unit}"
        if self.minimum is not None:
            return f"{label} must be at least {self.minimum}{unit}"
        if self.maximum is not None:
            return f"{label} must not exceed {self.maximum}{unit}"
        return f"{label} has no numeric limit in this standard"


# ---------------------------------------------------------------------------
# CPCB Designated Best Use criteria.
#
# Only the parameters each class actually specifies are listed. Class D says
# nothing about coliforms and Class E says nothing about BOD; inventing those
# limits to make the table look complete would be fabrication, so those
# combinations are simply absent and evaluate to "no applicable standard".
# ---------------------------------------------------------------------------
THRESHOLDS: tuple[Threshold, ...] = (
    # -- Class A ------------------------------------------------------------
    Threshold("total_coliform", DesignatedUse.A, maximum=50, unit="MPN/100mL"),
    Threshold("ph", DesignatedUse.A, minimum=6.5, maximum=8.5),
    Threshold("dissolved_oxygen", DesignatedUse.A, minimum=6.0, unit="mg/L"),
    Threshold("bod", DesignatedUse.A, maximum=2.0, unit="mg/L"),
    # -- Class B ------------------------------------------------------------
    Threshold("total_coliform", DesignatedUse.B, maximum=500, unit="MPN/100mL"),
    Threshold("ph", DesignatedUse.B, minimum=6.5, maximum=8.5),
    Threshold("dissolved_oxygen", DesignatedUse.B, minimum=5.0, unit="mg/L"),
    Threshold("bod", DesignatedUse.B, maximum=3.0, unit="mg/L"),
    # -- Class C ------------------------------------------------------------
    Threshold("total_coliform", DesignatedUse.C, maximum=5000, unit="MPN/100mL"),
    Threshold("ph", DesignatedUse.C, minimum=6.0, maximum=9.0),
    Threshold("dissolved_oxygen", DesignatedUse.C, minimum=4.0, unit="mg/L"),
    Threshold("bod", DesignatedUse.C, maximum=3.0, unit="mg/L"),
    # -- Class D ------------------------------------------------------------
    Threshold("ph", DesignatedUse.D, minimum=6.5, maximum=8.5),
    Threshold("dissolved_oxygen", DesignatedUse.D, minimum=4.0, unit="mg/L"),
    Threshold(
        "ammonia_n",
        DesignatedUse.D,
        maximum=1.2,
        unit="mg/L",
        note="Free ammonia as N.",
    ),
    # -- Class E ------------------------------------------------------------
    Threshold("ph", DesignatedUse.E, minimum=6.0, maximum=8.5),
    Threshold(
        "electrical_conductivity",
        DesignatedUse.E,
        maximum=2250,
        unit="uS/cm",
        note="Published as 2250 micro mhos/cm at 25 degC, equivalent to uS/cm.",
    ),
    Threshold("sodium_adsorption_ratio", DesignatedUse.E, maximum=26),
    Threshold("boron", DesignatedUse.E, maximum=2.0, unit="mg/L"),
)

_INDEX: dict[tuple[str, DesignatedUse], Threshold] = {
    (t.parameter_key, t.use): t for t in THRESHOLDS
}


def threshold_for(parameter_key: str, use: DesignatedUse) -> Threshold | None:
    """The limit for one parameter under one use, or ``None`` if unspecified."""
    return _INDEX.get((parameter_key, use))


def thresholds_for_use(use: DesignatedUse) -> list[Threshold]:
    """Every limit defined by one designated-use class."""
    return [t for t in THRESHOLDS if t.use == use]


def parameters_with_standards() -> set[str]:
    """Parameter keys covered by at least one standard."""
    return {t.parameter_key for t in THRESHOLDS}


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
class Compliance(StrEnum):
    """Outcome of comparing one measured value against one threshold."""

    WITHIN = "within"
    """Value satisfies the limit."""

    EXCEEDS = "exceeds"
    """Value is above a maximum."""

    BELOW = "below"
    """Value is under a minimum -- the dissolved-oxygen failure mode."""

    NO_STANDARD = "no_standard"
    """This standard sets no limit for this parameter. Not a pass."""

    NOT_MEASURED = "not_measured"
    """No value available. Emphatically not a pass."""


@dataclass(slots=True)
class Comparison:
    """A measured value judged against a cited limit."""

    parameter_key: str
    parameter_label: str
    value: float | None
    unit: str | None
    use: DesignatedUse
    compliance: Compliance
    threshold: Threshold | None = None
    exceedance_factor: float | None = None
    """How many times the limit the value is. Only set when it fails."""

    @property
    def failed(self) -> bool:
        """True only for a real, measured breach."""
        return self.compliance in (Compliance.EXCEEDS, Compliance.BELOW)

    def explain(self) -> str:
        """One sentence a non-specialist can read."""
        label = self.parameter_label
        if self.compliance is Compliance.NOT_MEASURED:
            return f"{label} was not measured in the latest observation."
        if self.compliance is Compliance.NO_STANDARD:
            return (
                f"{label} has no limit under {USE_LABELS[self.use]} "
                f"(class {self.use}), so no judgement is made."
            )

        unit = f" {self.unit}" if self.unit else ""
        assert self.threshold is not None
        if self.compliance is Compliance.EXCEEDS:
            times = (
                f" ({self.exceedance_factor:.1f}x the limit)"
                if self.exceedance_factor and self.exceedance_factor >= 1.5
                else ""
            )
            return (
                f"{label} is {self.value}{unit}, above the class "
                f"{self.use} limit of {self.threshold.maximum}{unit}{times}."
            )
        if self.compliance is Compliance.BELOW:
            return (
                f"{label} is {self.value}{unit}, below the class "
                f"{self.use} minimum of {self.threshold.minimum}{unit}."
            )
        return f"{label} is {self.value}{unit}, within the class {self.use} limit."

    def to_dict(self) -> dict:
        """Serialise, carrying the standard's provenance with the verdict."""
        return {
            "parameter": self.parameter_key,
            "label": self.parameter_label,
            "value": self.value,
            "unit": self.unit,
            "designated_use": str(self.use),
            "designated_use_label": USE_LABELS[self.use],
            "compliance": str(self.compliance),
            "failed": self.failed,
            "exceedance_factor": (
                round(self.exceedance_factor, 2) if self.exceedance_factor else None
            ),
            "limit_min": self.threshold.minimum if self.threshold else None,
            "limit_max": self.threshold.maximum if self.threshold else None,
            "standard_source": self.threshold.source if self.threshold else None,
            "standard_url": self.threshold.source_url if self.threshold else None,
            "explanation": self.explain(),
        }


def compare(
    parameter: Parameter | str,
    value: float | None,
    use: DesignatedUse = DEFAULT_USE,
) -> Comparison:
    """Judge one value against the standard for ``use``.

    A missing value yields ``NOT_MEASURED`` and a parameter the standard does
    not cover yields ``NO_STANDARD``. Neither is reported as compliance --
    that distinction is the whole point, because "we did not look" must never
    render as "it is fine".
    """
    param = BY_KEY[parameter] if isinstance(parameter, str) else parameter
    limit = threshold_for(param.key, use)

    if value is None:
        return Comparison(
            parameter_key=param.key,
            parameter_label=param.label,
            value=None,
            unit=param.unit,
            use=use,
            compliance=Compliance.NOT_MEASURED,
            threshold=limit,
        )

    if limit is None:
        return Comparison(
            parameter_key=param.key,
            parameter_label=param.label,
            value=value,
            unit=param.unit,
            use=use,
            compliance=Compliance.NO_STANDARD,
        )

    if limit.maximum is not None and value > limit.maximum:
        factor = value / limit.maximum if limit.maximum else None
        return Comparison(
            parameter_key=param.key,
            parameter_label=param.label,
            value=value,
            unit=param.unit,
            use=use,
            compliance=Compliance.EXCEEDS,
            threshold=limit,
            exceedance_factor=factor,
        )

    if limit.minimum is not None and value < limit.minimum:
        return Comparison(
            parameter_key=param.key,
            parameter_label=param.label,
            value=value,
            unit=param.unit,
            use=use,
            compliance=Compliance.BELOW,
            threshold=limit,
        )

    return Comparison(
        parameter_key=param.key,
        parameter_label=param.label,
        value=value,
        unit=param.unit,
        use=use,
        compliance=Compliance.WITHIN,
        threshold=limit,
    )


# ---------------------------------------------------------------------------
# CPCB polluted-river-stretch priority bands
#
# National criterion: a monitoring location with BOD above 3 mg/L is treated
# as polluted, and two or more such locations in continuous sequence on the
# same river constitute a Polluted River Stretch. The priority band scales the
# urgency of restoration.
# ---------------------------------------------------------------------------
PRS_BOD_THRESHOLD = 3.0
"""BOD (mg/L) above which CPCB treats a location as polluted."""

PRS_BANDS: tuple[tuple[str, float, float | None, str], ...] = (
    ("I", 30.0, None, "BOD above 30 mg/L"),
    ("II", 20.0, 30.0, "BOD 20-30 mg/L"),
    ("III", 10.0, 20.0, "BOD 10-20 mg/L"),
    ("IV", 6.0, 10.0, "BOD 6-10 mg/L"),
    ("V", 3.0, 6.0, "BOD 3-6 mg/L"),
)


def priority_band(bod: float | None) -> tuple[str, str] | None:
    """Map a BOD value onto its CPCB restoration-priority band.

    Returns ``(band, description)`` or ``None`` when BOD is missing or at or
    below the 3 mg/L polluted threshold.
    """
    if bod is None or bod <= PRS_BOD_THRESHOLD:
        return None
    for band, low, high, description in PRS_BANDS:
        if bod > low and (high is None or bod <= high):
            return band, description
    return None


def standards_summary() -> dict:
    """The standards in force, for the API and documentation."""
    by_use: dict[str, list[dict]] = {}
    for use in DesignatedUse:
        by_use[str(use)] = [
            {
                "parameter": t.parameter_key,
                "min": t.minimum,
                "max": t.maximum,
                "unit": t.unit,
                "describes": t.describe(),
            }
            for t in thresholds_for_use(use)
        ]
    return {
        "default_use": str(DEFAULT_USE),
        "default_use_label": USE_LABELS[DEFAULT_USE],
        "classes": {str(u): USE_LABELS[u] for u in DesignatedUse},
        "thresholds_by_use": by_use,
        "polluted_stretch": {
            "bod_threshold_mg_l": PRS_BOD_THRESHOLD,
            "bands": [
                {"priority": b, "min": lo, "max": hi, "describes": d}
                for b, lo, hi, d in PRS_BANDS
            ],
            "source": CPCB_PRS_SOURCE,
            "source_url": CPCB_PRS_URL,
        },
        "sources": [
            {"name": CPCB_CRITERIA_SOURCE, "url": CPCB_CRITERIA_URL},
            {"name": CPCB_PRS_SOURCE, "url": CPCB_PRS_URL},
        ],
        "notes": [
            "A parameter absent from a class is not judged under that class. "
            "No limit is invented to fill the table.",
            "Class C is the platform default because it matches the use to "
            "which most monitored Indian river stretches are actually put.",
        ],
    }
