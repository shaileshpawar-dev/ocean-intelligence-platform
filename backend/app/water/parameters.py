"""Canonical water-quality parameter registry.

Source datasets name the same quantity differently -- ``Potential of
Hydrogen (pH)`` in one CPCB file, ``pH`` in another, ``Amonia N (mgN/L)``
with the typo that is actually in the published column header. Storing those
strings verbatim would make every downstream query a guessing game, so each
source column is mapped onto a canonical parameter here, exactly once.

Three properties matter and are deliberately separated:

* **family** -- physical, chemical or biological. Mirrors how CPCB publishes
  the data and how a lab actually produces it.
* **canonical unit** -- the unit values are normalised into. A value whose
  source unit cannot be converted is stored with ``normalized_value = None``
  rather than silently reinterpreted.
* **higher_is_worse** -- the direction of concern. Dissolved oxygen is the
  parameter that breaks every naive "bigger number = worse" assumption, and
  getting it backwards would invert the status of every river in the country.

Nothing here encodes a threshold. Thresholds are a regulatory judgement that
varies by designated use, and they live in :mod:`app.water.standards` with
their own provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class ParameterFamily(StrEnum):
    """Which laboratory discipline produces the measurement."""

    PHYSICAL = "physical"
    CHEMICAL = "chemical"
    BIOLOGICAL = "biological"


@dataclass(frozen=True, slots=True)
class Parameter:
    """One canonical water-quality parameter."""

    key: str
    """Stable machine key, e.g. ``dissolved_oxygen``. Never changes."""

    label: str
    """Human-readable name for the UI."""

    family: ParameterFamily

    unit: str | None
    """Canonical unit. ``None`` for dimensionless or qualitative parameters."""

    higher_is_worse: bool | None
    """Direction of concern.

    ``True`` for pollutants, ``False`` for dissolved oxygen, ``None`` where
    concern is two-sided (pH) or the parameter is qualitative (colour).
    """

    aliases: tuple[str, ...] = ()
    """Source column headers, lower-cased, that map onto this parameter."""

    description: str = ""

    qualitative: bool = False
    """True when the value is a descriptive term rather than a number."""


def _norm(text: str) -> str:
    """Normalise a column header for alias matching.

    Collapses whitespace, strips punctuation and lower-cases, so
    ``"Iron(mg/L)"`` and ``"Iron (mg/L)"`` -- both of which appear in the
    published CPCB headers -- resolve to the same key.
    """
    text = text.strip().lower()
    text = re.sub(r"[\s_]+", " ", text)
    text = re.sub(r"[^a-z0-9()/+. ]", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# The registry
#
# Aliases are the *actual* published column headers observed in the CPCB
# resources on the National Water Data Portal, including their typos. They are
# recorded as found rather than corrected, because the ingestion adapter has to
# match what the source really sends.
# ---------------------------------------------------------------------------
PARAMETERS: tuple[Parameter, ...] = (
    # -- Physical -----------------------------------------------------------
    Parameter(
        key="temperature",
        label="Temperature",
        family=ParameterFamily.PHYSICAL,
        unit="degC",
        higher_is_worse=None,
        aliases=("temperature (oc)", "temperature (c)", "temperature"),
        description="Water temperature at the time of sampling.",
    ),
    Parameter(
        key="turbidity",
        label="Turbidity",
        family=ParameterFamily.PHYSICAL,
        unit="NTU",
        higher_is_worse=True,
        aliases=("turbidity (ntu)", "turbidity"),
        description="Cloudiness from suspended particles.",
    ),
    Parameter(
        key="electrical_conductivity",
        label="Electrical conductivity",
        family=ParameterFamily.PHYSICAL,
        unit="uS/cm",
        higher_is_worse=True,
        aliases=(
            "electric conductivity (ms/cm)",
            "electrical conductivity (ms/cm)",
            "conductivity (ms/cm)",
            "electric conductivity",
        ),
        description="Proxy for total dissolved ionic content.",
    ),
    Parameter(
        key="total_solids",
        label="Total solids",
        family=ParameterFamily.PHYSICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("total solids (mg/l)",),
    ),
    Parameter(
        key="colour",
        label="Colour",
        family=ParameterFamily.PHYSICAL,
        unit=None,
        higher_is_worse=None,
        aliases=("colour", "color"),
        qualitative=True,
    ),
    Parameter(
        key="odour",
        label="Odour",
        family=ParameterFamily.PHYSICAL,
        unit=None,
        higher_is_worse=None,
        aliases=("odour", "odor"),
        qualitative=True,
    ),
    # -- Chemical: the core oxygen / acidity set ----------------------------
    Parameter(
        key="dissolved_oxygen",
        label="Dissolved oxygen",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=False,
        aliases=("dissolved oxygen (mg/l)", "dissolved oxygen", "do (mg/l)"),
        description=(
            "Oxygen available to aquatic life. The one headline parameter "
            "where a LOWER value is worse."
        ),
    ),
    Parameter(
        key="ph",
        label="pH",
        family=ParameterFamily.CHEMICAL,
        unit=None,
        higher_is_worse=None,
        aliases=("potential of hydrogen (ph)", "ph", "p h"),
        description="Acidity/alkalinity. Concern is two-sided.",
    ),
    Parameter(
        key="total_dissolved_solids",
        label="Total dissolved solids",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("total dissolved solids (mg/l)", "tds (mg/l)"),
    ),
    # -- Chemical: nutrients ------------------------------------------------
    Parameter(
        key="ammonia_n",
        label="Ammonia (as N)",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        # The published header genuinely spells it "Amonia".
        aliases=("amonia n (mgn/l)", "ammonia n (mgn/l)", "ammonia (mgn/l)"),
    ),
    Parameter(
        key="nitrate_n",
        label="Nitrate (as N)",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("nitrate n (mgn/l)",),
    ),
    Parameter(
        key="nitrate",
        label="Nitrate",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("nitrate (mg/l)",),
    ),
    Parameter(
        key="nitrite_nitrate_n",
        label="Nitrite + nitrate (as N)",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("nitrite n+nitrate n (mgn/l)",),
    ),
    Parameter(
        key="total_phosphorus",
        label="Total phosphorus",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("total phosphorus (mgp/l)",),
    ),
    # -- Chemical: major ions / hardness ------------------------------------
    Parameter(
        key="chloride",
        label="Chloride",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("chloride (mg/l)",),
    ),
    Parameter(
        key="sulphate",
        label="Sulphate",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("sulphate (mg/l)", "sulfate (mg/l)"),
    ),
    Parameter(
        key="fluoride",
        label="Fluoride",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("fluoride (mg/l)",),
    ),
    Parameter(
        key="total_hardness",
        label="Total hardness",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("total hardness (mgcaco3/l)",),
    ),
    Parameter(
        key="total_alkalinity",
        label="Total alkalinity",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("total alkalinity (mg/l as caco3)",),
    ),
    Parameter(
        key="calcium",
        label="Calcium",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("calcium (mg/l)",),
    ),
    Parameter(
        key="magnesium",
        label="Magnesium",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("magnesium (mg/l)",),
    ),
    Parameter(
        key="sodium",
        label="Sodium",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("sodium (mg/l)",),
    ),
    Parameter(
        key="potassium",
        label="Potassium",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("potassium (mg/l)",),
    ),
    Parameter(
        key="carbonate",
        label="Carbonate",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("carbonate (mg/l)",),
    ),
    Parameter(
        key="bicarbonate",
        label="Bicarbonate",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("bicarbonate (mg/l)",),
    ),
    Parameter(
        key="boron",
        label="Boron",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("boron (mg/l)",),
    ),
    Parameter(
        key="hardness_calcium",
        label="Calcium hardness",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("hardness calcium (mgcaco3/l)",),
    ),
    Parameter(
        key="hardness_magnesium",
        label="Magnesium hardness",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=None,
        aliases=("hardness_magnesium (mg/l as caco3)",),
    ),
    Parameter(
        key="sodium_adsorption_ratio",
        label="Sodium adsorption ratio",
        family=ParameterFamily.CHEMICAL,
        unit=None,
        higher_is_worse=True,
        aliases=("sodium adsorption ratio (%)",),
    ),
    # -- Chemical: heavy metals --------------------------------------------
    Parameter(
        key="arsenic",
        label="Arsenic",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("arsenic (mg/l)",),
    ),
    Parameter(
        key="cadmium",
        label="Cadmium",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("cadmium (mg/l)",),
    ),
    Parameter(
        key="chromium",
        label="Chromium",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("chromium (mg/l)",),
    ),
    Parameter(
        key="lead",
        label="Lead",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("lead (mg/l)",),
    ),
    Parameter(
        key="mercury",
        label="Mercury",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        # Published without a space before the bracket.
        aliases=("mercury(mg/l)", "mercury (mg/l)"),
    ),
    Parameter(
        key="nickel",
        label="Nickel",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("nickel (mg/l)",),
    ),
    Parameter(
        key="iron",
        label="Iron",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("iron(mg/l)", "iron (mg/l)"),
    ),
    Parameter(
        key="manganese",
        label="Manganese",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("manganese (mg/l)",),
    ),
    Parameter(
        key="copper",
        label="Copper",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("copper (mg/l)",),
    ),
    Parameter(
        key="zinc",
        label="Zinc",
        family=ParameterFamily.CHEMICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("zinc (mg/l)",),
    ),
    # -- Biological ---------------------------------------------------------
    Parameter(
        key="bod",
        label="Biochemical oxygen demand",
        family=ParameterFamily.BIOLOGICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("biochemical oxygen demand (mg/l)", "bod (mg/l)", "bod"),
        description=(
            "Oxygen consumed by micro-organisms degrading organic matter. "
            "The primary indicator CPCB uses to identify polluted river "
            "stretches."
        ),
    ),
    Parameter(
        key="cod",
        label="Chemical oxygen demand",
        family=ParameterFamily.BIOLOGICAL,
        unit="mg/L",
        higher_is_worse=True,
        aliases=("chemical oxygen demand (mg/l)", "cod (mg/l)", "cod"),
    ),
    Parameter(
        key="fecal_coliform",
        label="Faecal coliform",
        family=ParameterFamily.BIOLOGICAL,
        unit="MPN/100mL",
        higher_is_worse=True,
        aliases=("fecal coliform (mpn/100ml)", "faecal coliform (mpn/100ml)"),
        description="Indicator of faecal contamination, i.e. sewage ingress.",
    ),
    Parameter(
        key="total_coliform",
        label="Total coliform",
        family=ParameterFamily.BIOLOGICAL,
        unit="MPN/100mL",
        higher_is_worse=True,
        aliases=("total coliform (mpn/100ml)",),
    ),
)


BY_KEY: dict[str, Parameter] = {p.key: p for p in PARAMETERS}

_BY_ALIAS: dict[str, Parameter] = {}
for _p in PARAMETERS:
    _BY_ALIAS[_norm(_p.key)] = _p
    _BY_ALIAS[_norm(_p.label)] = _p
    for _a in _p.aliases:
        _BY_ALIAS[_norm(_a)] = _p


def resolve(column: str) -> Parameter | None:
    """Map a source column header onto a canonical parameter.

    Returns ``None`` for an unrecognised header. The caller records that as a
    skipped column rather than inventing a parameter, so a schema change at
    the source shows up in the ingestion log instead of silently corrupting
    the database.
    """
    return _BY_ALIAS.get(_norm(column))


# ---------------------------------------------------------------------------
# Unit normalisation
#
# Only conversions that are exact and unambiguous are performed. Anything else
# returns None, which the caller stores as "not normalised" -- an honest gap
# rather than a guess.
# ---------------------------------------------------------------------------
_CONVERSIONS: dict[tuple[str, str], float] = {
    # CPCB publishes conductivity as mS/cm in the header, but the values --
    # e.g. 1500 for an urban lake -- are plainly uS/cm. See normalise_value.
    ("us/cm", "uS/cm"): 1.0,
    ("ms/cm", "uS/cm"): 1000.0,
    ("mg/l", "mg/L"): 1.0,
    ("ug/l", "mg/L"): 0.001,
    ("g/l", "mg/L"): 1000.0,
    ("ntu", "NTU"): 1.0,
    ("degc", "degC"): 1.0,
    ("c", "degC"): 1.0,
    ("mpn/100ml", "MPN/100mL"): 1.0,
}

# Values a source uses to mean "no measurement". Stored as missing, never 0.
MISSING_TOKENS = frozenset(
    {"", "-", "--", "na", "n/a", "nil", "null", "none", "nd", "not detected", "*"}
)


@dataclass(slots=True)
class ParsedValue:
    """Outcome of parsing one raw cell."""

    raw: str | None
    value: float | None = None
    normalized_value: float | None = None
    unit: str | None = None
    qualitative: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def is_missing(self) -> bool:
        """True when the source supplied no usable measurement."""
        return (
            self.value is None
            and self.normalized_value is None
            and self.qualitative is None
        )


_NUMERIC = re.compile(r"^[<>]?\s*(-?\d+(?:\.\d+)?)(?:\s*[eE]([+-]?\d+))?$")


def parse_value(parameter: Parameter, raw: object) -> ParsedValue:
    """Parse one raw cell into a value plus quality flags.

    Real source data contains ``'-'``, ``None``, empty strings, censored
    values such as ``'<0.01'``, and occasional stray text. Each is handled
    explicitly:

    * missing tokens produce a missing value -- **never** zero, because zero
      means "measured and found absent", which is a different claim;
    * censored values keep the numeric part and gain a ``censored`` flag;
    * unparseable text is preserved in ``raw`` with an ``unparseable`` flag
      so the record can be inspected rather than discarded.
    """
    if raw is None:
        return ParsedValue(raw=None)

    text = str(raw).strip()
    if text.lower() in MISSING_TOKENS:
        return ParsedValue(raw=None)

    if parameter.qualitative:
        return ParsedValue(raw=text, qualitative=text, unit=None)

    match = _NUMERIC.match(text)
    if not match:
        return ParsedValue(raw=text, flags=["unparseable"])

    flags: list[str] = []
    if text[0] in "<>":
        flags.append("censored")

    value = float(match.group(1))
    if match.group(2):
        value *= 10 ** int(match.group(2))

    if value < 0 and parameter.key not in {"temperature"}:
        flags.append("negative_implausible")

    normalized, unit = normalise_value(parameter, value)
    return ParsedValue(
        raw=text,
        value=value,
        normalized_value=normalized,
        unit=unit,
        flags=flags,
    )


def normalise_value(
    parameter: Parameter, value: float, source_unit: str | None = None
) -> tuple[float | None, str | None]:
    """Convert ``value`` into the parameter's canonical unit.

    Returns ``(None, None)`` when no exact conversion is known, so the caller
    stores the raw value and records that normalisation did not happen.
    """
    if parameter.unit is None:
        return value, None

    unit = (source_unit or parameter.unit).strip().lower().replace("μ", "u")
    factor = _CONVERSIONS.get((unit, parameter.unit))

    if factor is None:
        # Same unit spelled differently, e.g. "MG/L" vs "mg/L".
        if unit == parameter.unit.lower():
            factor = 1.0
        else:
            return None, None

    # Conductivity needs a judgement call. The CPCB header says mS/cm, but
    # the published magnitudes (hundreds to thousands) are uS/cm; a genuine
    # 1500 mS/cm would be forty times seawater. Treating the header as
    # authoritative would inflate every conductivity reading a thousandfold,
    # so magnitude decides and the assumption is documented here rather than
    # hidden in a constant.
    if parameter.key == "electrical_conductivity" and value > 100:
        factor = 1.0

    return value * factor, parameter.unit


def parameters_for_family(family: ParameterFamily) -> list[Parameter]:
    """Every canonical parameter in one family."""
    return [p for p in PARAMETERS if p.family == family]


def registry_summary() -> dict:
    """Composition of the registry, for the API and docs."""
    counts: dict[str, int] = {}
    for p in PARAMETERS:
        counts[str(p.family)] = counts.get(str(p.family), 0) + 1
    return {
        "total": len(PARAMETERS),
        "by_family": counts,
        "canonical_units": sorted({p.unit for p in PARAMETERS if p.unit}),
    }
