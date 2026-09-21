"""The reference standards the platform knows, as data.

This is the only place threshold values are written down. Application code
reads them from here (and from the ``reference_standards`` tables this module
seeds), so changing or adding a standard is a data change in one file, not a
hunt through the status engine.

Every standard records its legal basis, its source URL and how the values were
verified in this project. Nothing here is a platform invention.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ThresholdDef:
    """One limit for one parameter."""

    parameter: str
    threshold_type: str
    """``minimum``, ``maximum`` or ``range``."""

    minimum: float | None = None
    maximum: float | None = None
    desirable: float | None = None
    """Advisory level stricter than the limit, where the standard gives one.
    Exceeding it is reported but is not a breach."""

    unit: str | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class StandardDef:
    """A published standard, or one category within it."""

    code: str
    name: str
    issuing_body: str
    legal_basis: str
    source_url: str
    verified_note: str
    category: str | None = None
    version: str | None = None
    effective_date: str | None = None
    notes: str = ""
    thresholds: tuple[ThresholdDef, ...] = field(default_factory=tuple)

    def threshold(self, parameter: str) -> ThresholdDef | None:
        """The limit this standard sets for ``parameter``, if any."""
        return next((t for t in self.thresholds if t.parameter == parameter), None)


# ---------------------------------------------------------------------------
# Environment (Protection) Rules, 1986 -- item 93
#
# Read directly from the CPCB-hosted copy of the schedule (93-Water_Quality_
# Bathing.pdf) on 2026-09-21. CPCB applies the BOD criterion of this standard
# to river monitoring locations when it identifies polluted river stretches,
# which is why the platform uses it as the national assessment reference for
# rivers.
# ---------------------------------------------------------------------------
EP_BATHING = StandardDef(
    code="EP1986-93-BATHING",
    name="Primary Water Quality Criteria for Bathing Water",
    category="Water used for organised outdoor bathing",
    issuing_body="Ministry of Environment, Forest and Climate Change / CPCB",
    legal_basis="Environment (Protection) Rules, 1986 — Schedule, item 93",
    source_url=(
        "https://cpcb.nic.in/uploads/Industry-Specific-Standards/Effluent/"
        "93-Water_Quality_Bathing.pdf"
    ),
    verified_note=(
        "Values read from the CPCB-hosted PDF of the schedule on 2026-09-21. "
        "Faecal streptococci (100 desirable / 500 maximum MPN/100 mL) is also "
        "specified but is not a parameter in the ingested CPCB data."
    ),
    thresholds=(
        ThresholdDef(
            "fecal_coliform",
            "maximum",
            maximum=2500,
            desirable=500,
            unit="MPN/100mL",
            note="500 desirable, 2500 maximum permissible.",
        ),
        ThresholdDef("ph", "range", minimum=6.5, maximum=8.5),
        ThresholdDef("dissolved_oxygen", "minimum", minimum=5.0, unit="mg/L"),
        ThresholdDef(
            "bod",
            "maximum",
            maximum=3.0,
            unit="mg/L",
            note="BOD 3 day, 27 °C.",
        ),
    ),
)

_DBU_URL = "https://cpcb.nic.in/wqm/Designated_Best_Use_Water_Quality_Criteria.pdf"
_DBU_VERIFIED = (
    "Values cross-checked against independent sources quoting the CPCB "
    "criteria table on 2026-09-20; the CPCB PDF itself could not be fetched "
    "(expired TLS certificate at the time)."
)

DBU_CLASSES: tuple[StandardDef, ...] = (
    StandardDef(
        code="CPCB-DBU-A",
        name="Designated Best Use — Class A",
        category=(
            "Drinking water source without conventional treatment, after disinfection"
        ),
        issuing_body="Central Pollution Control Board",
        legal_basis="CPCB Designated Best Use Water Quality Criteria",
        source_url=_DBU_URL,
        verified_note=_DBU_VERIFIED,
        thresholds=(
            ThresholdDef("total_coliform", "maximum", maximum=50, unit="MPN/100mL"),
            ThresholdDef("ph", "range", minimum=6.5, maximum=8.5),
            ThresholdDef("dissolved_oxygen", "minimum", minimum=6.0, unit="mg/L"),
            ThresholdDef("bod", "maximum", maximum=2.0, unit="mg/L"),
        ),
    ),
    StandardDef(
        code="CPCB-DBU-B",
        name="Designated Best Use — Class B",
        category="Outdoor bathing (organised)",
        issuing_body="Central Pollution Control Board",
        legal_basis="CPCB Designated Best Use Water Quality Criteria",
        source_url=_DBU_URL,
        verified_note=_DBU_VERIFIED,
        thresholds=(
            ThresholdDef("total_coliform", "maximum", maximum=500, unit="MPN/100mL"),
            ThresholdDef("ph", "range", minimum=6.5, maximum=8.5),
            ThresholdDef("dissolved_oxygen", "minimum", minimum=5.0, unit="mg/L"),
            ThresholdDef("bod", "maximum", maximum=3.0, unit="mg/L"),
        ),
    ),
    StandardDef(
        code="CPCB-DBU-C",
        name="Designated Best Use — Class C",
        category="Drinking water source after conventional treatment and disinfection",
        issuing_body="Central Pollution Control Board",
        legal_basis="CPCB Designated Best Use Water Quality Criteria",
        source_url=_DBU_URL,
        verified_note=_DBU_VERIFIED,
        thresholds=(
            ThresholdDef("total_coliform", "maximum", maximum=5000, unit="MPN/100mL"),
            ThresholdDef("ph", "range", minimum=6.0, maximum=9.0),
            ThresholdDef("dissolved_oxygen", "minimum", minimum=4.0, unit="mg/L"),
            ThresholdDef("bod", "maximum", maximum=3.0, unit="mg/L"),
        ),
    ),
    StandardDef(
        code="CPCB-DBU-D",
        name="Designated Best Use — Class D",
        category="Propagation of wildlife and fisheries",
        issuing_body="Central Pollution Control Board",
        legal_basis="CPCB Designated Best Use Water Quality Criteria",
        source_url=_DBU_URL,
        verified_note=_DBU_VERIFIED,
        thresholds=(
            ThresholdDef("ph", "range", minimum=6.5, maximum=8.5),
            ThresholdDef("dissolved_oxygen", "minimum", minimum=4.0, unit="mg/L"),
            ThresholdDef(
                "ammonia_n",
                "maximum",
                maximum=1.2,
                unit="mg/L",
                note="Free ammonia as N.",
            ),
        ),
    ),
    StandardDef(
        code="CPCB-DBU-E",
        name="Designated Best Use — Class E",
        category="Irrigation, industrial cooling, controlled waste disposal",
        issuing_body="Central Pollution Control Board",
        legal_basis="CPCB Designated Best Use Water Quality Criteria",
        source_url=_DBU_URL,
        verified_note=_DBU_VERIFIED,
        thresholds=(
            ThresholdDef("ph", "range", minimum=6.0, maximum=8.5),
            ThresholdDef(
                "electrical_conductivity",
                "maximum",
                maximum=2250,
                unit="uS/cm",
                note="Published as 2250 micromhos/cm at 25 °C.",
            ),
            ThresholdDef("sodium_adsorption_ratio", "maximum", maximum=26),
            ThresholdDef("boron", "maximum", maximum=2.0, unit="mg/L"),
        ),
    ),
)

ALL_STANDARDS: tuple[StandardDef, ...] = (EP_BATHING, *DBU_CLASSES)
BY_CODE: dict[str, StandardDef] = {s.code: s for s in ALL_STANDARDS}

# Designated-use class letter -> standard code, for sources that record a
# class ("C") rather than a code.
DBU_BY_CLASS: dict[str, str] = {s.code[-1]: s.code for s in DBU_CLASSES}
