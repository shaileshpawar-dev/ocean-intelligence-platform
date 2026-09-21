"""Reference selection and comparison.

    observation -> which reference applies? -> compare -> comparison result

Phase 1 compared every water body against CPCB class C by default. That was
an invisible assumption: class C is a *designated use*, and nobody had
designated it for most of the water bodies it was applied to. This module
replaces the default with an explicit selection, made in this order:

1. **User-selected** -- the reader chose a standard to compare against.
2. **Designated use recorded for the water body** by an authoritative source.
3. **Station classification** from the source (none is published today).
4. **National assessment category** -- CPCB assesses *river* monitoring
   locations against the Primary Water Quality Criteria for Bathing Water
   (Environment (Protection) Rules 1986, item 93) when it identifies polluted
   stretches. Rivers therefore get that reference, and the reason says so.
5. **None.** No comparison is made, the result says why, and the measured
   values are still shown.

Every comparison carries the code, name, legal basis and URL of the standard
it used, and the basis on which that standard was selected.

Threshold values live in :mod:`app.water.reference_catalog`, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.enums import WaterBodyType
from app.water.parameters import BY_KEY, Parameter
from app.water.reference_catalog import (
    ALL_STANDARDS,
    BY_CODE,
    DBU_BY_CLASS,
    DBU_CLASSES,
    EP_BATHING,
    StandardDef,
    ThresholdDef,
)


class DesignatedUse(StrEnum):
    """CPCB Designated-Best-Use classes, selectable explicitly by a reader."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


USE_LABELS: dict[DesignatedUse, str] = {
    DesignatedUse(code[-1]): s.category or s.name
    for code, s in ((d.code, d) for d in DBU_CLASSES)
}


class SelectionBasis(StrEnum):
    """Why a reference standard applies to a water body."""

    USER_SELECTED = "user_selected"
    WATER_BODY_DESIGNATED_USE = "water_body_designated_use"
    STATION_CLASSIFICATION = "station_classification"
    NATIONAL_ASSESSMENT_CATEGORY = "national_assessment_category"
    NONE = "none"


BASIS_LABELS: dict[SelectionBasis, str] = {
    SelectionBasis.USER_SELECTED: "Selected by you",
    SelectionBasis.WATER_BODY_DESIGNATED_USE: (
        "Designated use recorded for this water body"
    ),
    SelectionBasis.STATION_CLASSIFICATION: "Station classification from the source",
    SelectionBasis.NATIONAL_ASSESSMENT_CATEGORY: "National assessment category",
    SelectionBasis.NONE: "No applicable reference",
}

# Types CPCB assesses against the bathing criteria when identifying polluted
# river stretches. Only these receive a reference without an explicit choice.
NATIONAL_ASSESSMENT_TYPES = frozenset({WaterBodyType.RIVER, WaterBodyType.RIVER_STRETCH})

_NO_REFERENCE_REASONS: dict[str, str] = {
    WaterBodyType.GROUNDWATER: (
        "Groundwater is judged against the drinking-water standard IS 10500, "
        "which is not loaded in this platform."
    ),
    WaterBodyType.COASTAL: (
        "Coastal waters are classified SW-I to SW-V by designated use; no class "
        "is recorded for this location."
    ),
    WaterBodyType.MARINE: (
        "Marine waters are classified SW-I to SW-V by designated use; no class "
        "is recorded for this location."
    ),
}
_DEFAULT_NO_REFERENCE = (
    "No designated use is recorded for this water body, and CPCB's national "
    "assessment criterion applies to river locations only. Choose a "
    "designated-use class to compare against one explicitly."
)


@dataclass(frozen=True, slots=True)
class ReferenceSelection:
    """The standard that applies, and why -- or why none does."""

    standard: StandardDef | None
    basis: SelectionBasis
    reason: str

    @property
    def available(self) -> bool:
        """True when a comparison can be made."""
        return self.standard is not None

    def to_dict(self) -> dict:
        """Serialise with the standard's provenance."""
        s = self.standard
        return {
            "available": self.available,
            "basis": str(self.basis),
            "basis_label": BASIS_LABELS[self.basis],
            "reason": self.reason,
            "standard_code": s.code if s else None,
            "standard_name": s.name if s else None,
            "category": s.category if s else None,
            "legal_basis": s.legal_basis if s else None,
            "source_url": s.source_url if s else None,
            "verified_note": s.verified_note if s else None,
        }


def select_reference(
    water_type: str | WaterBodyType,
    *,
    explicit: str | None = None,
    designated_use: str | None = None,
    station_class: str | None = None,
) -> ReferenceSelection:
    """Choose the reference standard for a water body, or decline to.

    Args:
        water_type: the water body's type.
        explicit: a standard code or class letter chosen by the reader.
        designated_use: class recorded for the water body by a source.
        station_class: class published for the station by a source.
    """
    if explicit:
        code = DBU_BY_CLASS.get(explicit.upper(), explicit.upper())
        standard = BY_CODE.get(code)
        if standard is not None:
            return ReferenceSelection(
                standard,
                SelectionBasis.USER_SELECTED,
                f"Compared against {standard.name} because you selected it.",
            )

    for value, basis, what in (
        (designated_use, SelectionBasis.WATER_BODY_DESIGNATED_USE, "water body"),
        (station_class, SelectionBasis.STATION_CLASSIFICATION, "station"),
    ):
        if value and value.upper() in DBU_BY_CLASS:
            standard = BY_CODE[DBU_BY_CLASS[value.upper()]]
            return ReferenceSelection(
                standard,
                basis,
                f"The source records designated use class {value.upper()} for this "
                f"{what}.",
            )

    if str(water_type) in {str(t) for t in NATIONAL_ASSESSMENT_TYPES}:
        return ReferenceSelection(
            EP_BATHING,
            SelectionBasis.NATIONAL_ASSESSMENT_CATEGORY,
            "CPCB assesses river monitoring locations against the Primary Water "
            "Quality Criteria for Bathing Water (Environment (Protection) Rules "
            "1986, item 93) when identifying polluted river stretches, so rivers "
            "are compared against that standard.",
        )

    return ReferenceSelection(
        None,
        SelectionBasis.NONE,
        _NO_REFERENCE_REASONS.get(str(water_type), _DEFAULT_NO_REFERENCE),
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
class Compliance(StrEnum):
    """Outcome of comparing one measured value against one threshold."""

    WITHIN = "within"
    EXCEEDS = "exceeds"
    BELOW = "below"
    NO_STANDARD = "no_standard"
    """The selected standard sets no limit for this parameter. Not a pass."""

    NOT_MEASURED = "not_measured"
    """No value available. Emphatically not a pass."""

    NO_REFERENCE = "no_reference"
    """No reference standard applies to this water body at all."""


@dataclass(slots=True)
class Comparison:
    """A measured value judged against a cited limit."""

    parameter_key: str
    parameter_label: str
    value: float | None
    unit: str | None
    compliance: Compliance
    standard: StandardDef | None = None
    threshold: ThresholdDef | None = None
    exceedance_factor: float | None = None
    above_desirable: bool = False

    @property
    def failed(self) -> bool:
        """True only for a real, measured breach."""
        return self.compliance in (Compliance.EXCEEDS, Compliance.BELOW)

    @property
    def use(self) -> str | None:
        """Short label of the standard, for sentences."""
        return self.standard.code if self.standard else None

    def explain(self) -> str:
        """One sentence a non-specialist can read."""
        label = self.parameter_label
        unit = f" {self.unit}" if self.unit else ""
        name = self.standard.name if self.standard else "the selected standard"
        if self.compliance is Compliance.NOT_MEASURED:
            return f"{label} was not measured in the latest observation."
        if self.compliance is Compliance.NO_REFERENCE:
            return f"{label} is {self.value}{unit}; no reference standard applies."
        if self.compliance is Compliance.NO_STANDARD:
            return f"{label} is {self.value}{unit}; {name} sets no limit for it."
        assert self.threshold is not None
        if self.compliance is Compliance.EXCEEDS:
            times = (
                f" ({self.exceedance_factor:.1f}x the limit)"
                if self.exceedance_factor and self.exceedance_factor >= 1.5
                else ""
            )
            return (
                f"{label} is {self.value}{unit}, above the limit of "
                f"{self.threshold.maximum}{unit} in {name}{times}."
            )
        if self.compliance is Compliance.BELOW:
            return (
                f"{label} is {self.value}{unit}, below the minimum of "
                f"{self.threshold.minimum}{unit} in {name}."
            )
        note = (
            f" It is above the desirable level of {self.threshold.desirable}{unit}."
            if self.above_desirable
            else ""
        )
        return f"{label} is {self.value}{unit}, within the limit in {name}.{note}"

    def to_dict(self) -> dict:
        """Serialise, carrying the standard's provenance with the verdict."""
        t, s = self.threshold, self.standard
        return {
            "parameter": self.parameter_key,
            "label": self.parameter_label,
            "value": self.value,
            "unit": self.unit,
            "compliance": str(self.compliance),
            "failed": self.failed,
            "evidence_type": "REFERENCE_COMPARISON",
            "exceedance_factor": (
                round(self.exceedance_factor, 2) if self.exceedance_factor else None
            ),
            "above_desirable": self.above_desirable,
            "threshold_type": t.threshold_type if t else None,
            "limit_min": t.minimum if t else None,
            "limit_max": t.maximum if t else None,
            "desirable": t.desirable if t else None,
            "standard_code": s.code if s else None,
            "standard_name": s.name if s else None,
            "standard_source": s.legal_basis if s else None,
            "standard_url": s.source_url if s else None,
            # Kept for clients built against Phase 1.
            "designated_use": s.code[-1] if s and s.code.startswith("CPCB-DBU") else None,
            "explanation": self.explain(),
        }


def _as_standard(
    reference: StandardDef | DesignatedUse | str | None,
) -> StandardDef | None:
    if reference is None or isinstance(reference, StandardDef):
        return reference
    text = str(reference).upper()
    return BY_CODE.get(DBU_BY_CLASS.get(text, text))


def compare(
    parameter: Parameter | str,
    value: float | None,
    reference: StandardDef | DesignatedUse | str | None,
) -> Comparison:
    """Judge one value against the standard ``reference``.

    ``reference`` may be a standard, a class letter or ``None`` (no applicable
    reference). A missing value is ``NOT_MEASURED`` and an uncovered parameter
    is ``NO_STANDARD``; neither is ever reported as compliance.
    """
    param = BY_KEY[parameter] if isinstance(parameter, str) else parameter
    standard = _as_standard(reference)
    base = {
        "parameter_key": param.key,
        "parameter_label": param.label,
        "unit": param.unit,
    }

    if value is None:
        return Comparison(
            value=None, compliance=Compliance.NOT_MEASURED, standard=standard, **base
        )
    if standard is None:
        return Comparison(value=value, compliance=Compliance.NO_REFERENCE, **base)

    limit = standard.threshold(param.key)
    if limit is None:
        return Comparison(
            value=value, compliance=Compliance.NO_STANDARD, standard=standard, **base
        )

    if limit.maximum is not None and value > limit.maximum:
        return Comparison(
            value=value,
            compliance=Compliance.EXCEEDS,
            standard=standard,
            threshold=limit,
            exceedance_factor=value / limit.maximum if limit.maximum else None,
            **base,
        )
    if limit.minimum is not None and value < limit.minimum:
        return Comparison(
            value=value,
            compliance=Compliance.BELOW,
            standard=standard,
            threshold=limit,
            **base,
        )
    return Comparison(
        value=value,
        compliance=Compliance.WITHIN,
        standard=standard,
        threshold=limit,
        above_desirable=bool(limit.desirable is not None and value > limit.desirable),
        **base,
    )


def threshold_for(parameter_key: str, use: DesignatedUse | str) -> ThresholdDef | None:
    """The limit a designated-use class sets for a parameter."""
    standard = _as_standard(use)
    return standard.threshold(parameter_key) if standard else None


def governed_parameters(standard: StandardDef) -> set[str]:
    """Parameter keys a standard sets limits for."""
    return {t.parameter for t in standard.thresholds}


# ---------------------------------------------------------------------------
# CPCB polluted-river-stretch bands (context only)
#
# These bands classify *stretches* that CPCB has identified. The platform
# does not identify stretches itself and never labels a water body a polluted
# stretch from one observation; the bands are exposed so that an imported
# official classification can be explained.
# ---------------------------------------------------------------------------
PRS_BOD_THRESHOLD = 3.0

PRS_BANDS: tuple[tuple[str, float, float | None, str], ...] = (
    ("I", 30.0, None, "BOD above 30 mg/L"),
    ("II", 20.0, 30.0, "BOD 20-30 mg/L"),
    ("III", 10.0, 20.0, "BOD 10-20 mg/L"),
    ("IV", 6.0, 10.0, "BOD 6-10 mg/L"),
    ("V", 3.0, 6.0, "BOD 3-6 mg/L"),
)

CPCB_PRS_SOURCE = "CPCB — Polluted River Stretches for Restoration of Water Quality"
CPCB_PRS_URL = "https://cpcb.nic.in/reports-3/"


def priority_band(bod: float | None) -> tuple[str, str] | None:
    """The CPCB priority band a BOD value falls in (context, not a verdict)."""
    if bod is None or bod <= PRS_BOD_THRESHOLD:
        return None
    for band, low, high, description in PRS_BANDS:
        if bod > low and (high is None or bod <= high):
            return band, description
    return None


def standards_summary() -> dict:
    """The standards and the selection rules in force, for API and docs."""
    return {
        "selection_order": [
            {"basis": str(b), "label": BASIS_LABELS[b]} for b in SelectionBasis
        ],
        "national_assessment": {
            "applies_to": sorted(str(t) for t in NATIONAL_ASSESSMENT_TYPES),
            "standard_code": EP_BATHING.code,
            "reason": select_reference(WaterBodyType.RIVER).reason,
        },
        "standards": [
            {
                "code": s.code,
                "name": s.name,
                "category": s.category,
                "issuing_body": s.issuing_body,
                "legal_basis": s.legal_basis,
                "source_url": s.source_url,
                "verified_note": s.verified_note,
                "thresholds": [
                    {
                        "parameter": t.parameter,
                        "label": BY_KEY[t.parameter].label
                        if t.parameter in BY_KEY
                        else t.parameter,
                        "type": t.threshold_type,
                        "min": t.minimum,
                        "max": t.maximum,
                        "desirable": t.desirable,
                        "unit": t.unit,
                        "note": t.note or None,
                    }
                    for t in s.thresholds
                ],
            }
            for s in ALL_STANDARDS
        ],
        "polluted_stretch_bands": [
            {"priority": b, "min": lo, "max": hi, "describes": d}
            for b, lo, hi, d in PRS_BANDS
        ],
        "notes": [
            "No standard is applied by default. Rivers are compared against the "
            "national assessment criterion; other water bodies are compared only "
            "when a designated use is recorded or chosen explicitly.",
            "A parameter a standard does not govern is never treated as compliant.",
            "Polluted-stretch bands describe CPCB-identified stretches; the "
            "platform does not assign that classification from observations.",
        ],
    }
