"""Water Intelligence question answering.

    QUESTION -> IDENTIFY -> OBSERVE -> RESEARCH -> ANALYZE -> REPORT

The existing research assistant answers from documents. This one answers
mostly from the *database*, because the questions people ask about Indian
water -- "what is the status of Mithi?", "which rivers near Pune are
polluted?" -- are questions about records, and a record lookup is both more
accurate and more checkable than any passage retrieval.

Three properties are enforced structurally rather than by prompt:

**Facts come from records, not from a model.** Every number in an answer is
read from an observation row and is cited with its date, station and source
reference. The answer text is assembled from those rows by templates. No
language model is on the path that produces a value, so there is no path by
which one can invent a value.

**Absence is reported, not filled.** A question about a parameter nobody
measured gets an explicit statement that no measurement exists -- not an
estimate, not a regional average, not a plausible-sounding figure.

**"Current" is never said.** Every status is the latest available one, with
its date, and the freshness verdict is stated alongside it.

The five stages are a bounded linear pipeline: each runs once, in order, and
records the tool calls it makes, so a reader can see exactly which lookups
produced an answer. There is no planner and no loop.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.water import District, MonitoringStation, State, WaterBody
from app.models.water_geo import City
from app.services import water_service as ws
from app.water import geo
from app.water.matching import expand_place_aliases, normalise_name
from app.water.parameters import BY_KEY, PARAMETERS

PIPELINE_VERSION = "water-rag-2.0.0"

# Radius used when a question says "near X" without a distance. Large enough
# to take in a metropolitan district's water bodies, small enough that "near
# Mumbai" does not return the whole Konkan coast.
DEFAULT_RADIUS_KM = 25.0
MAX_RADIUS_KM = 300.0

POLLUTED_BANDS = frozenset({"POLLUTED_STRETCH", "HIGH_CONCERN", "ELEVATED"})
HIGH_CONCERN_BANDS = frozenset({"POLLUTED_STRETCH", "HIGH_CONCERN"})

# Words that would otherwise resolve to water bodies with generic names.
_STOP_ENTITIES = frozenset(
    {
        "SEA",
        "WATER",
        "RIVER",
        "LAKE",
        "TANK",
        "SEA WATER",
        "GROUNDWATER",
        "INDIA",
        "THE",
        "NEAR",
        "WITH",
        "WHAT",
        "WHICH",
        "WHERE",
        "FROM",
        "LAST",
        "LATEST",
        "STATUS",
        "SHOW",
        "ABOUT",
        "OVER",
        "TIME",
        "RIGHT",
        "POND",
        "CANAL",
        "DRAIN",
        "CREEK",
        "BEACH",
        "WELL",
        "STP",
        "B W",
    }
)

# Extra phrasings people use for parameters, beyond the registry's labels.
_PARAMETER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "bod": ("bod", "biochemical oxygen demand", "biological oxygen demand"),
    "cod": ("cod", "chemical oxygen demand"),
    "dissolved_oxygen": ("dissolved oxygen", "do level", "oxygen"),
    "ph": ("ph", "acidity", "alkalinity"),
    "fecal_coliform": ("fecal coliform", "faecal coliform", "coliform", "sewage"),
    "total_coliform": ("total coliform",),
    "turbidity": ("turbidity", "turbid", "muddy"),
    "electrical_conductivity": ("conductivity", "salinity"),
    "total_dissolved_solids": ("tds", "total dissolved solids", "dissolved solids"),
}


# Plural type words in a question narrow the result to that kind of water body.
_TYPE_WORDS: tuple[tuple[str, str], ...] = (
    (r"\brivers?\b", "river"),
    (r"\blakes?\b", "lake"),
    (r"\b(ponds?|tanks?)\b", "pond"),
    (r"\bcreeks?\b", "creek"),
    (r"\b(reservoirs?|dams?)\b", "reservoir"),
    (r"\b(coast|coastal|beach(es)?|sea)\b", "coastal"),
    (r"\b(groundwater|wells?)\b", "groundwater"),
)


class Intent(StrEnum):
    """What the question is asking for."""

    STATUS = "status"
    PARAMETER = "parameter"
    TREND = "trend"
    COMPARE = "compare"
    NEARBY = "nearby"
    FRESHNESS = "freshness"
    SOURCE = "source"
    STANDARDS = "standards"
    UNKNOWN = "unknown"


class AnswerStatus(StrEnum):
    """How much the evidence supports the answer."""

    GROUNDED = "grounded"
    """Built from records, every figure cited."""

    PARTIAL = "partial"
    """Some of what was asked is supported; the rest is stated as missing."""

    NO_EVIDENCE = "no_evidence"
    """Nothing in the records or corpus supports an answer. None is given."""


@dataclass(slots=True)
class ToolCall:
    """One lookup the pipeline made, recorded for the trace."""

    stage: str
    tool: str
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: float

    def to_dict(self) -> dict:
        """Serialise for the API."""
        return {
            "stage": self.stage,
            "tool": self.tool,
            "arguments": self.arguments,
            "result": self.result_summary,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass(slots=True)
class Resolution:
    """Entities found in the question by deterministic lookup."""

    water_bodies: list[WaterBody] = field(default_factory=list)
    districts: list[tuple[District, State]] = field(default_factory=list)
    states: list[State] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    radius_km: float | None = None
    wants_polluted: bool = False
    wants_no_recent: bool = False
    water_types: list[str] = field(default_factory=list)
    cities: list[City] = field(default_factory=list)
    wants_stations: bool = False
    wants_high_concern: bool = False

    def describe(self) -> dict:
        """What was resolved, for the trace and the UI."""
        return {
            "water_bodies": [b.name for b in self.water_bodies],
            "cities": [c.name for c in self.cities],
            "districts": [f"{d.name}, {s.name}" for d, s in self.districts],
            "states": [s.name for s in self.states],
            "parameters": [BY_KEY[p].label for p in self.parameters if p in BY_KEY],
            "radius_km": self.radius_km,
            "filter_polluted": self.wants_polluted,
            "filter_no_recent_data": self.wants_no_recent,
            "filter_high_concern": self.wants_high_concern,
            "wants_stations": self.wants_stations,
            "water_types": self.water_types,
        }


@dataclass(slots=True)
class Citation:
    """A record an answer relies on."""

    position: int
    kind: str
    """``observation``, ``status``, ``document`` or ``water_body``."""

    title: str
    detail: str
    evidence_type: str
    water_body_slug: str | None = None
    station_id: int | None = None
    observed_at: str | None = None
    source: str | None = None
    source_reference: str | None = None
    url: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def to_dict(self) -> dict:
        """Serialise, including the map target a click should fly to."""
        return {
            "position": self.position,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "evidence_type": self.evidence_type,
            "water_body_slug": self.water_body_slug,
            "station_id": self.station_id,
            "observed_at": self.observed_at,
            "source": self.source,
            "source_reference": self.source_reference,
            "url": self.url,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "href": (
                f"/app/map?focus={self.water_body_slug}" if self.water_body_slug else None
            ),
        }


@dataclass(slots=True)
class WaterAnswer:
    """A grounded answer plus everything needed to audit it."""

    question: str
    intent: Intent
    status: AnswerStatus
    headline: str
    sections: list[dict] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    map_action: dict | None = None
    resolution: dict = field(default_factory=dict)
    trace: list[ToolCall] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise for the API."""
        return {
            "question": self.question,
            "intent": str(self.intent),
            "status": str(self.status),
            "headline": self.headline,
            "sections": self.sections,
            "citations": [c.to_dict() for c in self.citations],
            "limitations": self.limitations,
            "map_action": self.map_action,
            "resolution": self.resolution,
            "trace": [t.to_dict() for t in self.trace],
            "pipeline_version": PIPELINE_VERSION,
            "llm_used": False,
            "notes": [
                "Every figure is read from a stored observation and cited. No "
                "language model produced any value in this answer.",
            ],
        }


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------
class _Tracer:
    """Runs lookups and records them, so the trace is never hand-written."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def call(self, stage: str, tool: str, fn: Any, /, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = fn(**kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        self.calls.append(
            ToolCall(
                stage=stage,
                tool=tool,
                arguments={k: _trace_value(v) for k, v in kwargs.items() if k != "db"},
                result_summary=_summarise(result),
                duration_ms=elapsed,
            )
        )
        return result


def _trace_value(value: Any) -> Any:
    """A JSON-safe stand-in for a tool argument, for the recorded trace.

    ORM objects are recorded by type and name, long lists by their length;
    the trace documents what was asked, not a dump of the database.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        if len(value) > 5:
            return f"<{len(value)} items>"
        return [_trace_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _trace_value(v) for k, v in list(value.items())[:10]}
    name = getattr(value, "name", None) or getattr(value, "slug", None)
    return f"{type(value).__name__}:{name}" if name else type(value).__name__


def _summarise(result: Any) -> str:
    if result is None:
        return "nothing found"
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    if isinstance(result, dict):
        if "name" in result:
            return str(result["name"])
        return f"{len(result)} field(s)"
    return type(result).__name__


# ---------------------------------------------------------------------------
# Stage 1: IDENTIFY
# ---------------------------------------------------------------------------
def classify_intent(question: str) -> Intent:
    """Decide what kind of answer is wanted, from the wording alone."""
    q = question.lower()
    if re.search(r"\bcompare\b|\bversus\b|\bvs\.?\b|\bdifference between\b", q):
        return Intent.COMPARE
    if re.search(r"\b(near|around|close to|within \d+\s*km)\b", q):
        return Intent.NEARBY
    if re.search(r"\b(trend|improv|worse|worsen|over time|changed|history)", q):
        return Intent.TREND
    if re.search(
        r"\b(last measurement|last measured|no recent data|how old|"
        r"when was|latest data)\b",
        q,
    ):
        return Intent.FRESHNESS
    if re.search(r"\b(source|which dataset|who measured|where .* come from)\b", q):
        return Intent.SOURCE
    if re.search(r"\b(standard|criteria|criterion|threshold|limit|class [a-e])\b", q):
        return Intent.STANDARDS
    if re.search(r"\b(which|where|list)\b", q):
        return Intent.PARAMETER
    if re.search(r"\b(status|polluted|clean|safe|quality|condition|how is)\b", q):
        return Intent.STATUS
    return Intent.UNKNOWN


def _question_tokens(question: str) -> str:
    # "Bengaluru" must find the source's "Bangalore Urban".
    return f" {expand_place_aliases(normalise_name(question))} "


def _find_parameters(question: str) -> list[str]:
    q = f" {question.lower()} "
    found: list[str] = []
    for key, phrases in _PARAMETER_SYNONYMS.items():
        if any(re.search(rf"\b{re.escape(p)}\b", q) for p in phrases):
            found.append(key)
    for param in PARAMETERS:
        label = param.label.lower()
        if param.key not in found and re.search(rf"\b{re.escape(label)}\b", q):
            found.append(param.key)
    # "Oxygen demand" contains "oxygen"; do not also claim dissolved oxygen.
    mentions_do = re.search(r"dissolved oxygen|\bdo\b", q)
    if ("bod" in found or "cod" in found) and not mentions_do:
        found = [f for f in found if f != "dissolved_oxygen"]
    return found


def resolve_entities(db: Session, question: str) -> Resolution:
    """Match water bodies, places and parameters by deterministic lookup.

    Longest match wins, so "Mula Mutha" is not mistaken for "Mutha", and a
    water body is only matched on whole words, so "Tapi" does not match
    inside "Tapiola".
    """
    text = _question_tokens(question)
    resolution = Resolution(parameters=_find_parameters(question))

    lowered = question.lower()
    resolution.wants_polluted = bool(
        re.search(
            r"\b(polluted|pollution|contaminated|elevated|high concern|"
            r"unsafe|dirty)\b",
            lowered,
        )
    )
    resolution.wants_no_recent = bool(re.search(r"no recent data", lowered))
    resolution.wants_high_concern = bool(re.search(r"\bhigh[- ]concern\b", lowered))
    resolution.wants_stations = bool(re.search(r"\bstations?\b", lowered))

    # "Which rivers..." must not return creeks and beaches.
    for pattern, wtype in _TYPE_WORDS:
        if re.search(pattern, lowered):
            resolution.water_types.append(wtype)

    radius = re.search(r"within\s+(\d+(?:\.\d+)?)\s*km", lowered)
    if radius:
        resolution.radius_km = min(float(radius.group(1)), MAX_RADIUS_KM)

    # -- Water bodies ------------------------------------------------------
    candidates: list[tuple[int, WaterBody]] = []
    for body in db.scalars(select(WaterBody)):
        name = body.normalized_name.strip()
        if not name or name in _STOP_ENTITIES or len(name) < 3:
            continue
        # A short core ("KIM", "RED", "SON") is an ordinary word too often to
        # match alone; it counts only with its type word ("Kim River").
        full = normalise_name(body.name)
        names = [
            n
            for n in (name, full, *(normalise_name(a) for a in (body.aliases or [])))
            if n and (len(n) >= 4 or " " in n) and n not in _STOP_ENTITIES
        ]
        hit = next((n for n in names if f" {n} " in text), None)
        if hit:
            candidates.append((len(hit), body))
    candidates.sort(key=lambda pair: -pair[0])

    chosen: list[WaterBody] = []
    taken: list[str] = []
    for _, body in candidates:
        name = body.normalized_name
        # Skip a shorter name wholly contained in one already chosen.
        if any(f" {name} " in f" {t} " for t in taken):
            continue
        chosen.append(body)
        taken.append(name)
    resolution.water_bodies = chosen[:4]

    # -- Cities (curated district groupings) -------------------------------
    for city in db.scalars(select(City)):
        names = [city.name, *(city.aliases or [])]
        if any(f" {normalise_name(n)} " in text for n in names):
            resolution.cities.append(city)
    city_districts = {d for c in resolution.cities for d in (c.district_ids or [])}
    city_heads = {normalise_name(c.name) for c in resolution.cities}

    # -- Districts and states -----------------------------------------------
    for district, state in db.execute(
        select(District, State).join(State, State.id == District.state_id)
    ):
        dname = normalise_name(district.name)
        # "Mumbai" should find "Mumbai Suburban" and "Mumbai City".
        head = dname.split()[0] if dname else ""
        if district.id in city_districts:
            continue  # already represented by the city
        head_hit = len(head) >= 4 and f" {head} " in text and head not in city_heads
        if (dname and f" {dname} " in text) or head_hit:
            resolution.districts.append((district, state))

    for state in db.scalars(select(State)):
        if f" {normalise_name(state.name)} " in text:
            resolution.states.append(state)

    return resolution


# ---------------------------------------------------------------------------
# Helpers for later stages
# ---------------------------------------------------------------------------
def _fmt_value(value: float | None, unit: str | None) -> str:
    if value is None:
        return "not measured"
    number = f"{value:,.0f}" if abs(value) >= 1000 else f"{value:g}"
    return f"{number} {unit}".strip() if unit else number


def _day(iso: str | None) -> str:
    if not iso:
        return "an unknown date"
    return datetime.fromisoformat(iso).strftime("%d %b %Y")


def _filter_by_breach(db: Session, bodies: list[dict], parameter: str) -> list[dict]:
    """Keep only bodies whose latest measurement of ``parameter`` breached.

    Bodies where the parameter was never measured are dropped, not kept: they
    cannot be said to have breached anything, and they cannot be said to be
    compliant either.
    """
    kept = []
    for summary in bodies:
        body = db.get(WaterBody, summary["id"])
        reading = next(
            (r for r in ws.latest_parameters(db, body) if r["parameter"] == parameter),
            None,
        )
        if reading and reading["comparison"]["failed"]:
            kept.append(summary)
    return kept


def _band_words(status: str | None) -> str:
    """Render a status code as lower-case words for a sentence."""
    return (status or "not assessed").replace("_", " ").lower()


def _centre_of(places: list[tuple[District, State]]) -> tuple[float, float] | None:
    points = [
        (d.centroid_lat, d.centroid_lon)
        for d, _ in places
        if d.centroid_lat is not None and d.centroid_lon is not None
    ]
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def _bbox(bodies: list[dict]) -> list[float] | None:
    located = [
        (b["latitude"], b["longitude"])
        for b in bodies
        if b.get("latitude") is not None and b.get("longitude") is not None
    ]
    if not located:
        return None
    lats = [p[0] for p in located]
    lons = [p[1] for p in located]
    pad = 0.05
    return [min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad]


def _map_action(bodies: list[dict], *, focus: str | None = None) -> dict | None:
    """Structured instruction telling the map what to show."""
    slugs = [b["slug"] for b in bodies if b.get("slug")]
    if not slugs:
        return None
    return {
        "type": "highlight",
        "water_body_slugs": slugs,
        "focus": focus or (slugs[0] if len(slugs) == 1 else None),
        "bbox": _bbox(bodies),
        "href": f"/app/map?highlight={','.join(slugs[:40])}",
    }


# ---------------------------------------------------------------------------
# Answer builders (stages 2-5 for each intent)
# ---------------------------------------------------------------------------
def _body_status_section(
    db: Session,
    tracer: _Tracer,
    body: WaterBody,
    citations: list[Citation],
    wanted_parameters: list[str],
    limitations: list[str],
) -> dict:
    """OBSERVE + ANALYZE for one water body."""
    detail = tracer.call(
        "OBSERVE",
        "get_water_body_detail",
        ws.get_water_body_detail,
        db=db,
        slug=body.slug,
    )
    present = detail["status_detail"]
    historical = detail.get("latest_available_status")

    status_line = (
        f"{historical['label']} as of {_day(historical.get('as_of'))}"
        if historical
        else "No measurement has ever been recorded"
    )
    for classification in (historical or {}).get("source_classifications", []):
        if classification.get("priority"):
            status_line += (
                f" (listed by {classification['source']} as priority "
                f"{classification['priority']})"
            )
            break

    citations.append(
        Citation(
            position=len(citations) + 1,
            kind="status",
            title=f"{body.name} — status",
            detail=status_line,
            evidence_type="DERIVED_STATUS",
            water_body_slug=body.slug,
            observed_at=historical.get("as_of") if historical else None,
            source=_status_source(detail),
            latitude=body.centroid_lat,
            longitude=body.centroid_lon,
        )
    )
    status_ref = len(citations)

    parameters = detail["parameters"]
    if wanted_parameters:
        shown = [p for p in parameters if p["parameter"] in wanted_parameters]
        for key in wanted_parameters:
            if not any(p["parameter"] == key for p in parameters):
                label = BY_KEY[key].label if key in BY_KEY else key
                limitations.append(
                    f"No {label.lower()} measurement is recorded for {body.name}. "
                    "No value is estimated in its place."
                )
    else:
        headline_keys = (
            "bod",
            "dissolved_oxygen",
            "ph",
            "fecal_coliform",
            "total_coliform",
            "cod",
            "turbidity",
        )
        shown = [p for p in parameters if p["parameter"] in headline_keys]

    indicators = []
    for reading in shown:
        citations.append(
            Citation(
                position=len(citations) + 1,
                kind="observation",
                title=f"{reading['label']} at {reading['station'] or body.name}",
                detail=_fmt_value(reading["value"], reading["unit"]),
                evidence_type="MEASURED",
                water_body_slug=body.slug,
                observed_at=reading["observed_at"],
                source="CPCB via National Water Data Portal",
                source_reference=reading["source_reference"],
                latitude=body.centroid_lat,
                longitude=body.centroid_lon,
            )
        )
        comparison = reading["comparison"]
        verdict = _verdict_words(comparison)
        indicators.append(
            {
                "label": reading["label"],
                "value": _fmt_value(reading["value"], reading["unit"]),
                "verdict": verdict,
                "failed": comparison["failed"],
                "observed_at": reading["observed_at"],
                "cite": len(citations),
            }
        )

    for image in detail.get("imagery", [])[:1]:
        proxy = image.get("proxy") or {}
        if proxy.get("median") is None:
            continue
        citations.append(
            Citation(
                position=len(citations) + 1,
                kind="satellite",
                title=f"{body.name} — {image['sensor']} scene",
                detail=(
                    f"{proxy['label']}: {proxy['median']:.3f} (index, no unit) on "
                    f"{image['acquisition_date']}. Not a measurement."
                ),
                evidence_type="SATELLITE_OBSERVED",
                water_body_slug=body.slug,
                observed_at=image["acquisition_date"],
                source=f"{image['source']} via {image['provider']}",
                source_reference=image["scene_id"],
                latitude=body.centroid_lat,
                longitude=body.centroid_lon,
            )
        )

    sources = detail.get("sources_by_recency") or []
    if len(sources) > 1:
        newest, *older = sources
        limitations.append(
            f"{body.name} is measured by more than one agency. Newest: "
            f"{newest['name']} ({_day(newest['latest_observed_at'])}). Also: "
            + "; ".join(f"{s['name']} ({_day(s['latest_observed_at'])})" for s in older)
            + ". Their observations are kept separate and never combined."
        )

    return {
        "water_body": body.name,
        "slug": body.slug,
        "source_breakdown": [
            {
                "key": s["key"],
                "name": s["name"],
                "organisation": s["organisation"],
                "latest_observed_at": s["latest_observed_at"],
                "observation_count": s["observation_count"],
                "observation_method": s.get("observation_method"),
            }
            for s in sources
        ],
        "evidence_layers": _evidence_layers(detail, historical, indicators),
        "place": ", ".join(x for x in [detail.get("district"), detail.get("state")] if x),
        "present_status": present["label"],
        "present_reason": present["freshness"]["summary"],
        "latest_available_status": status_line,
        "newest_source": _newest_source_phrase(detail),
        "status_cite": status_ref,
        "indicators": indicators,
        "why": (historical or present)["reasons"][:3],
        "latest_observed_at": detail.get("latest_observed_at"),
        "sources": [s["name"] for s in detail["sources"]],
        "reference": detail["reference"],
        "summary": detail,
    }


def _status_source(detail: dict) -> str:
    reference = detail.get("reference") or {}
    name = reference.get("standard_name")
    return (
        f"OceanAI status engine, compared against {name}"
        if name
        else "OceanAI status engine (no applicable reference)"
    )


def _newest_source_phrase(detail: dict) -> str:
    """Say which source is newest, e.g. Newest data: CWC, 21 Apr 2025.

    Returns an empty string when the water body has only one source.
    """
    sources = detail.get("sources_by_recency") or []
    if not sources:
        return ""
    newest = sources[0]
    phrase = f"Newest data: {newest['name']}, {_day(newest['latest_observed_at'])}"
    if len(sources) > 1:
        older = sources[1]
        phrase += f"; {older['name']} stops at {_day(older['latest_observed_at'])}"
    return phrase + "."


def _evidence_layers(detail: dict, historical: dict | None, indicators: list) -> dict:
    """The same answer, split by kind of evidence, so none is mistaken for another."""
    reference = detail.get("reference") or {}
    image = next(iter(detail.get("imagery") or []), None)
    proxy = (image or {}).get("proxy") or {}
    return {
        "MEASURED": {
            "count": len(indicators),
            "latest": detail.get("latest_observed_at"),
            "source": ", ".join(s["name"] for s in detail.get("sources", [])),
            "by_source": [
                {
                    "name": s["name"],
                    "latest": s["latest_observed_at"],
                    "observations": s["observation_count"],
                }
                for s in (detail.get("sources_by_recency") or [])
            ],
        },
        "REFERENCE_COMPARISON": {
            "standard": reference.get("standard_name"),
            "basis": reference.get("basis_label"),
            "unavailable_reason": None
            if reference.get("standard_code")
            else reference.get("reason"),
        },
        "SOURCE_CLASSIFICATION": (historical or {}).get("source_classifications", []),
        "DERIVED_STATUS": {
            "label": (historical or {}).get("label"),
            "as_of": (historical or {}).get("as_of"),
            "describes_present_state": False,
        },
        "SATELLITE_OBSERVED": (
            {
                "label": proxy.get("label"),
                "value": proxy.get("median"),
                "date": image.get("acquisition_date"),
                "calibrated": False,
            }
            if proxy.get("median") is not None
            else None
        ),
    }


def _verdict_words(comparison: dict) -> str:
    """Plain words for a REFERENCE_COMPARISON, naming the standard used."""
    standard = comparison.get("standard_name") or "the reference"
    return {
        "exceeds": f"above the {standard} limit",
        "below": f"below the {standard} minimum",
        "within": f"within the {standard} limit",
        "no_standard": f"{standard} sets no limit for this parameter",
        "no_reference": "no applicable reference; shown as measured",
        "not_measured": "not measured",
    }.get(comparison["compliance"], comparison["compliance"])


def _answer_status(
    db: Session, tracer: _Tracer, question: str, resolution: Resolution, intent: Intent
) -> WaterAnswer:
    citations: list[Citation] = []
    limitations: list[str] = []
    sections = [
        _body_status_section(
            db, tracer, body, citations, resolution.parameters, limitations
        )
        for body in resolution.water_bodies
    ]

    tracer.call("ANALYZE", "compare_against_standard", lambda: sections)

    first = sections[0]
    headline = (
        f"{first['water_body']}: {first['latest_available_status']}. "
        f"Right now: {first['present_status'].lower()} — "
        f"{first['present_reason']}"
    )
    if len(sections) > 1:
        headline = "; ".join(
            f"{s['water_body']}: {s['latest_available_status']}" for s in sections
        )

    for section in sections:
        reference = section["reference"]
        if reference.get("standard_code"):
            limitations.append(
                f"{section['water_body']} is compared against "
                f"{reference['standard_name']} ({reference['basis_label'].lower()}). "
                "Another designated use can change the verdict."
            )
        else:
            limitations.append(
                f"{section['water_body']}: reference comparison unavailable. "
                f"{reference['reason']}"
            )

    status = AnswerStatus.GROUNDED
    if resolution.parameters and not any(s["indicators"] for s in sections):
        status = AnswerStatus.NO_EVIDENCE
        headline = limitations[0]
    elif any("No " in lim and "measurement is recorded" in lim for lim in limitations):
        status = AnswerStatus.PARTIAL

    bodies = [ws.summarise_body(db, b) for b in resolution.water_bodies]
    for s in sections:
        s.pop("summary", None)

    return WaterAnswer(
        question=question,
        intent=intent,
        status=status,
        headline=headline,
        sections=[{"kind": "water_body", **s} for s in sections],
        citations=citations,
        limitations=limitations,
        map_action=_map_action(
            bodies, focus=bodies[0]["slug"] if len(bodies) == 1 else None
        ),
    )


def _answer_trend(
    db: Session, tracer: _Tracer, question: str, resolution: Resolution
) -> WaterAnswer:
    body = resolution.water_bodies[0]
    parameter = resolution.parameters[0] if resolution.parameters else "bod"
    trend = tracer.call(
        "OBSERVE",
        "get_parameter_trend",
        ws.parameter_trend,
        db=db,
        slug=body.slug,
        parameter=parameter,
    )
    citations: list[Citation] = []
    label = BY_KEY[parameter].label

    if not trend or trend["point_count"] < 2:
        return WaterAnswer(
            question=question,
            intent=Intent.TREND,
            status=AnswerStatus.NO_EVIDENCE,
            headline=(
                f"{body.name} has fewer than two {label.lower()} observations, so "
                "no trend can be stated."
            ),
            limitations=["A single measurement is not a trend."],
            map_action=_map_action([ws.summarise_body(db, body)], focus=body.slug),
        )

    points = trend["points"]
    by_year: dict[int, list[float]] = {}
    for p in points:
        by_year.setdefault(datetime.fromisoformat(p["observed_at"]).year, []).append(
            p["value"]
        )
    years = sorted(by_year)
    first_year, last_year = years[0], years[-1]
    first_mean = sum(by_year[first_year]) / len(by_year[first_year])
    last_mean = sum(by_year[last_year]) / len(by_year[last_year])

    tracer.call("ANALYZE", "compare_annual_means", lambda: by_year)

    unit = trend["unit"] or ""
    worse_if_higher = BY_KEY[parameter].higher_is_worse
    if first_year == last_year:
        direction = "all observations fall within a single year"
        verdict = "no year-on-year comparison is possible"
    else:
        change = last_mean - first_mean
        rel = abs(change) / first_mean if first_mean else 0
        if rel < 0.10:
            verdict = "broadly unchanged"
        elif worse_if_higher is None:
            verdict = "changed"
        elif (change < 0) == bool(worse_if_higher):
            verdict = "improved"
        else:
            verdict = "worsened"
        direction = (
            f"mean {label.lower()} moved from {first_mean:.1f} {unit} in "
            f"{first_year} ({len(by_year[first_year])} samples) to "
            f"{last_mean:.1f} {unit} in {last_year} "
            f"({len(by_year[last_year])} samples)"
        )

    citations.append(
        Citation(
            position=1,
            kind="observation",
            title=f"{label} series, {body.name}",
            detail=f"{trend['point_count']} observations, "
            f"{_day(trend['first_observed_at'])} to {_day(trend['last_observed_at'])}",
            evidence_type="MEASURED",
            water_body_slug=body.slug,
            observed_at=trend["last_observed_at"],
            source="CPCB via National Water Data Portal",
            latitude=body.centroid_lat,
            longitude=body.centroid_lon,
        )
    )

    missing_years = [y for y in range(first_year, last_year + 1) if y not in by_year]
    limitations = [
        "Annual means of monthly grab samples. Individual months vary widely, "
        "and a comparison of two years is not a statistical trend test.",
    ]
    if missing_years:
        limitations.append(
            "No observations exist for "
            + ", ".join(str(y) for y in missing_years)
            + "; nothing is interpolated across that gap."
        )

    return WaterAnswer(
        question=question,
        intent=Intent.TREND,
        status=AnswerStatus.GROUNDED,
        headline=f"{body.name}: {label.lower()} has {verdict} — {direction}.",
        sections=[
            {
                "kind": "trend",
                "water_body": body.name,
                "slug": body.slug,
                "parameter": parameter,
                "label": label,
                "unit": unit,
                "annual_means": {
                    str(y): round(sum(v) / len(v), 2) for y, v in by_year.items()
                },
                "samples_per_year": {str(y): len(v) for y, v in by_year.items()},
                "verdict": verdict,
                "cite": 1,
            }
        ],
        citations=citations,
        limitations=limitations,
        map_action=_map_action([ws.summarise_body(db, body)], focus=body.slug),
    )


def _answer_nearby(
    db: Session, tracer: _Tracer, question: str, resolution: Resolution
) -> WaterAnswer:
    if resolution.cities:
        return _answer_city(db, tracer, question, resolution)
    centre: tuple[float, float] | None = None
    place = ""
    if resolution.districts:
        centre = _centre_of(resolution.districts)
        names = sorted({d.name for d, _ in resolution.districts})
        place = " / ".join(names)
    elif resolution.water_bodies:
        body = resolution.water_bodies[0]
        if body.centroid_lat is not None:
            centre = (body.centroid_lat, body.centroid_lon)
            place = body.name

    if centre is None:
        return WaterAnswer(
            question=question,
            intent=Intent.NEARBY,
            status=AnswerStatus.NO_EVIDENCE,
            headline=(
                "The place in this question could not be matched to any district "
                "or water body in the ingested data, so no spatial search was run."
            ),
            limitations=[
                "Only districts present in ingested CPCB data can be used as a "
                "search centre."
            ],
        )

    radius = resolution.radius_km or DEFAULT_RADIUS_KM
    place_phrase = f"any monitoring station in {place}" if resolution.districts else place
    if resolution.districts:
        # A district is represented by its own stations, not one averaged
        # point: see water_service.water_bodies_near_districts.
        found = tracer.call(
            "OBSERVE",
            "water_bodies_near_districts",
            ws.water_bodies_near_districts,
            db=db,
            district_ids=[d.id for d, _ in resolution.districts],
            radius_km=radius,
            limit=100,
        )
    else:
        found = tracer.call(
            "OBSERVE",
            "water_bodies_near",
            ws.water_bodies_near,
            db=db,
            latitude=centre[0],
            longitude=centre[1],
            radius_km=radius,
            limit=100,
        )
    found = _apply_resolution_filters(db, tracer, found, resolution)

    citations = [
        Citation(
            position=i + 1,
            kind="water_body",
            title=b["name"],
            detail=(
                f"{b['distance_km']} km away · "
                f"{_band_words(b.get('latest_available_status'))} "
                f"when last measured ({_day(b.get('latest_observed_at'))})"
            ),
            evidence_type="DERIVED_STATUS",
            water_body_slug=b["slug"],
            observed_at=b.get("latest_observed_at"),
            source="OceanAI status engine (reference chosen per water body)",
            latitude=b.get("latitude"),
            longitude=b.get("longitude"),
        )
        for i, b in enumerate(found[:25])
    ]

    qualifier = (
        "with a polluted or elevated status when last measured "
        if (resolution.wants_polluted)
        else ""
    )
    if not found:
        return WaterAnswer(
            question=question,
            intent=Intent.NEARBY,
            status=AnswerStatus.NO_EVIDENCE,
            headline=(
                f"No monitored water bodies {qualifier}were found within "
                f"{radius:g} km of {place_phrase}."
            ),
            limitations=[
                "Absence from this list means no matching monitored water body, "
                "not that the area's water is clean.",
            ],
        )

    return WaterAnswer(
        question=question,
        intent=Intent.NEARBY,
        status=AnswerStatus.GROUNDED,
        headline=(
            f"{len(found)} monitored water bod{'y' if len(found) == 1 else 'ies'} "
            f"{qualifier}within {radius:g} km of {place_phrase}."
        ),
        sections=[
            {
                "kind": "list",
                "centre": {"latitude": centre[0], "longitude": centre[1]},
                "radius_km": radius,
                "items": [
                    {
                        "name": b["name"],
                        "slug": b["slug"],
                        "water_type": b["water_type"],
                        "distance_km": b["distance_km"],
                        "latest_available_status": b.get("latest_available_status"),
                        "latest_observed_at": b.get("latest_observed_at"),
                        "cite": i + 1,
                    }
                    for i, b in enumerate(found[:25])
                ],
            }
        ],
        citations=citations,
        limitations=[
            "Statuses are as of each water body's most recent measurement, with "
            "its date; the source extracts are years old, so none describes the "
            "present.",
            (
                "A district is represented by its own monitoring stations; each "
                "distance is from the nearest of them to the water body's "
                "station-mean position. The source publishes no district boundary."
                if resolution.districts
                else "Distances are measured to the mean position of each water "
                "body's monitoring stations."
            ),
        ],
        map_action=_map_action(found),
    )


def _apply_resolution_filters(
    db: Session, tracer: _Tracer, found: list[dict], resolution: Resolution
) -> list[dict]:
    if resolution.wants_high_concern:
        found = [
            b for b in found if b.get("latest_available_status") in HIGH_CONCERN_BANDS
        ]
    elif resolution.wants_polluted:
        found = [b for b in found if b.get("latest_available_status") in POLLUTED_BANDS]
    if resolution.water_types:
        found = [b for b in found if b.get("water_type") in resolution.water_types]
    if resolution.parameters:
        found = tracer.call(
            "ANALYZE",
            "filter_by_measured_breach",
            _filter_by_breach,
            db=db,
            bodies=found,
            parameter=resolution.parameters[0],
        )
    return found


def _stations_near_box(
    db: Session, box: tuple[float, float, float, float], radius_km: float
) -> list[dict]:
    """Stations within ``radius_km`` of a (min_lon, min_lat, max_lon, max_lat) box."""
    pad = radius_km / 100.0 + 0.01
    rows = db.scalars(
        select(MonitoringStation).where(
            MonitoringStation.latitude.between(box[1] - pad, box[3] + pad),
            MonitoringStation.longitude.between(box[0] - pad * 1.2, box[2] + pad * 1.2),
        )
    ).all()
    shape = {
        "type": "Polygon",
        "coordinates": [
            [
                [box[0], box[1]],
                [box[2], box[1]],
                [box[2], box[3]],
                [box[0], box[3]],
                [box[0], box[1]],
            ]
        ],
    }
    out = []
    for s in ws.summarise_stations(db, list(rows)):
        d = geo.distance_km(shape, s["longitude"], s["latitude"])
        if d <= radius_km:
            out.append({**s, "distance_km": round(d, 2)})
    out.sort(key=lambda s: (s["distance_km"], -(s["observation_count"] or 0)))
    return out


def _answer_city(
    db: Session, tracer: _Tracer, question: str, resolution: Resolution
) -> WaterAnswer:
    """Spatial questions about a curated city, measured from its extent."""
    city = resolution.cities[0]
    if city.min_lat is None:
        return WaterAnswer(
            question=question,
            intent=Intent.NEARBY,
            status=AnswerStatus.NO_EVIDENCE,
            headline=(
                f"{city.name} has no mapped extent (no district polygon was found "
                "for it), so no spatial search was run."
            ),
            limitations=[city.position_source],
        )
    near = bool(re.search(r"\b(near|around|close to|within)\b", question.lower()))
    radius = resolution.radius_km or (DEFAULT_RADIUS_KM if near else 0.0)
    box = (city.min_lon, city.min_lat, city.max_lon, city.max_lat)
    where = f"within {radius:g} km of {city.name}" if radius else f"in {city.name}"
    definition = f"{city.name} is defined here as: {city.definition_note}"
    extent_note = (
        "Distances are measured from the city's extent (the bounding box of its "
        "districts), so everything inside the city is at 0 km."
    )

    if resolution.wants_stations:
        stations = tracer.call(
            "OBSERVE",
            "stations_near_city",
            _stations_near_box,
            db=db,
            box=box,
            radius_km=radius,
        )
        if not stations:
            return WaterAnswer(
                question=question,
                intent=Intent.NEARBY,
                status=AnswerStatus.NO_EVIDENCE,
                headline=f"No CPCB monitoring station is recorded {where}.",
                limitations=[definition, extent_note],
            )
        citations = [
            Citation(
                position=i + 1,
                kind="station",
                title=s["name"],
                detail=(
                    f"{s['distance_km']} km · {s['observation_count']} observations, "
                    f"latest {_day(s.get('latest_observed_at'))}"
                ),
                evidence_type="MEASURED",
                water_body_slug=s.get("water_body_slug"),
                observed_at=s.get("latest_observed_at"),
                source="CPCB via National Water Data Portal",
                latitude=s["latitude"],
                longitude=s["longitude"],
            )
            for i, s in enumerate(stations[:25])
        ]
        return WaterAnswer(
            question=question,
            intent=Intent.NEARBY,
            status=AnswerStatus.GROUNDED,
            headline=(
                f"{len(stations)} CPCB monitoring station"
                f"{'' if len(stations) == 1 else 's'} {where}."
            ),
            sections=[
                {
                    "kind": "stations",
                    "items": [
                        {
                            "name": s["name"],
                            "id": s["id"],
                            "water_body": s.get("water_body"),
                            "water_body_slug": s.get("water_body_slug"),
                            "distance_km": s["distance_km"],
                            "latest_observed_at": s.get("latest_observed_at"),
                            "cite": i + 1,
                        }
                        for i, s in enumerate(stations[:25])
                    ],
                }
            ],
            citations=citations,
            limitations=[definition, extent_note],
            map_action={
                "type": "fit",
                "bbox": [city.min_lat, city.min_lon, city.max_lat, city.max_lon],
                "href": f"/app/map?city={city.slug}",
            },
        )

    from app.services import geo_service as gs

    found = tracer.call(
        "OBSERVE",
        "water_bodies_near_city",
        gs.bodies_near_city,
        db=db,
        city=city,
        radius_km=radius,
    )
    found = _apply_resolution_filters(db, tracer, found, resolution)
    kinds = (
        " / ".join(f"{t}s" for t in resolution.water_types)
        if resolution.water_types
        else "monitored water bodies"
    )
    qualifier = (
        "with a high-concern status when last measured "
        if resolution.wants_high_concern
        else "with a polluted or elevated status when last measured "
        if resolution.wants_polluted
        else ""
    )
    limitations = [
        definition,
        extent_note,
        "Statuses are as of each water body's most recent measurement, with its "
        "date; none describes the present.",
    ]
    if not found:
        return WaterAnswer(
            question=question,
            intent=Intent.NEARBY,
            status=AnswerStatus.NO_EVIDENCE,
            headline=f"No {kinds} {qualifier}were found {where}.",
            limitations=[
                "Absence from this list means no matching monitored water body, "
                "not that the area's water is clean.",
                *limitations,
            ],
        )
    citations = [
        Citation(
            position=i + 1,
            kind="water_body",
            title=b["name"],
            detail=(
                f"{b['distance_km']} km · "
                f"{_band_words(b.get('latest_available_status'))} when last "
                f"measured ({_day(b.get('latest_observed_at'))})"
            ),
            evidence_type="DERIVED_STATUS",
            water_body_slug=b["slug"],
            observed_at=b.get("latest_observed_at"),
            source="OceanAI status engine (reference chosen per water body)",
            latitude=b.get("latitude"),
            longitude=b.get("longitude"),
        )
        for i, b in enumerate(found[:25])
    ]
    noun = (
        (" / ".join(resolution.water_types) if len(found) == 1 else kinds)
        if resolution.water_types
        else "monitored water body"
        if len(found) == 1
        else "monitored water bodies"
    )
    return WaterAnswer(
        question=question,
        intent=Intent.NEARBY,
        status=AnswerStatus.GROUNDED,
        headline=(f"{len(found)} {noun} {qualifier}{where}."),
        sections=[
            {
                "kind": "list",
                "city": {"name": city.name, "slug": city.slug},
                "radius_km": radius,
                "items": [
                    {
                        "name": b["name"],
                        "slug": b["slug"],
                        "water_type": b["water_type"],
                        "distance_km": b["distance_km"],
                        "latest_available_status": b.get("latest_available_status"),
                        "latest_observed_at": b.get("latest_observed_at"),
                        "cite": i + 1,
                    }
                    for i, b in enumerate(found[:25])
                ],
            }
        ],
        citations=citations,
        limitations=limitations,
        map_action=_map_action(found),
    )


def _answer_parameter_filter(
    db: Session, tracer: _Tracer, question: str, resolution: Resolution
) -> WaterAnswer:
    """Answer questions like "Which rivers in Maharashtra have elevated BOD?"."""
    parameter = resolution.parameters[0] if resolution.parameters else None
    state = resolution.states[0] if resolution.states else None
    # "Rivers in Goa": a place and a kind, no filter -- list them all.
    listing = bool(
        state
        and resolution.water_types
        and not parameter
        and not (
            resolution.wants_polluted
            or resolution.wants_high_concern
            or resolution.wants_no_recent
        )
    )
    # The type is filtered in SQL: a state can hold several hundred bodies,
    # and filtering after a row limit silently truncated large states.
    filters = ws.WaterBodyFilters(
        state=state.slug if state else None,
        water_type=resolution.water_types[0]
        if len(resolution.water_types) == 1
        else None,
    )
    bodies, _ = tracer.call(
        "OBSERVE",
        "list_water_bodies",
        ws.list_water_bodies,
        db=db,
        filters=filters,
        limit=1000,
    )

    if resolution.water_types:
        bodies = [b for b in bodies if b["water_type"] in resolution.water_types]

    matches: list[tuple[dict, dict]] = []
    for summary in bodies:
        if listing:
            matches.append((summary, {}))
        elif parameter:
            # Readings only when a parameter was asked about (was N+1 always).
            body = db.get(WaterBody, summary["id"])
            readings = ws.latest_parameters(db, body)
            reading = next((r for r in readings if r["parameter"] == parameter), None)
            if reading and reading["comparison"]["failed"]:
                matches.append((summary, reading))
        elif (
            (
                resolution.wants_high_concern
                and summary.get("latest_available_status") in HIGH_CONCERN_BANDS
            )
            or (
                resolution.wants_polluted
                and not resolution.wants_high_concern
                and summary.get("latest_available_status") in POLLUTED_BANDS
            )
            or (resolution.wants_no_recent and summary.get("status") == "NO_RECENT_DATA")
        ):
            matches.append((summary, {}))

    tracer.call("ANALYZE", "filter_failing", lambda: matches)
    scope = f" in {state.name}" if state else ""

    if (
        not listing
        and not parameter
        and not (
            resolution.wants_polluted
            or resolution.wants_high_concern
            or resolution.wants_no_recent
        )
    ):
        return _no_evidence(question, Intent.PARAMETER)

    label = BY_KEY[parameter].label.lower() if parameter else "status"
    if not matches:
        return WaterAnswer(
            question=question,
            intent=Intent.PARAMETER,
            status=AnswerStatus.NO_EVIDENCE,
            headline=(
                f"No monitored water body{scope} breached its {label} limit at its "
                "most recent measurement."
                if parameter
                else f"No matching water bodies{scope}."
            ),
            limitations=[
                "Water bodies where this parameter was not measured cannot appear "
                "here; their absence is not evidence of compliance.",
            ],
        )

    citations = []
    items = []
    for i, (summary, reading) in enumerate(matches[:30]):
        detail = (
            f"{reading['label']} {_fmt_value(reading['value'], reading['unit'])} on "
            f"{_day(reading['observed_at'])}"
            if reading
            else f"{_band_words(summary.get('latest_available_status'))}"
            f" as of {_day(summary.get('latest_observed_at'))}"
        )
        citations.append(
            Citation(
                position=i + 1,
                kind="observation" if reading else "water_body",
                title=summary["name"],
                detail=detail,
                evidence_type="MEASURED" if reading else "INFERRED",
                water_body_slug=summary["slug"],
                observed_at=(reading or {}).get("observed_at")
                or summary.get("latest_observed_at"),
                source="CPCB via National Water Data Portal",
                source_reference=(reading or {}).get("source_reference"),
                latitude=summary.get("latitude"),
                longitude=summary.get("longitude"),
            )
        )
        items.append(
            {
                "name": summary["name"],
                "slug": summary["slug"],
                "water_type": summary["water_type"],
                "detail": detail,
                "latest_available_status": summary.get("latest_available_status"),
                # The date belongs on the item, not only in the citation: the
                # limitation below promises each one is dated, and a status
                # rendered without its date is the thing this platform exists
                # to avoid. The parameter's own reading dates it when there is
                # one; otherwise the water body's latest observation does.
                "observed_at": (reading or {}).get("observed_at")
                or summary.get("latest_observed_at"),
                "latest_observed_at": summary.get("latest_observed_at"),
                "cite": i + 1,
            }
        )

    what = f"{label} outside its reference limit" if parameter else "matching status"
    plural = "water body" if len(matches) == 1 else "water bodies"
    return WaterAnswer(
        question=question,
        intent=Intent.PARAMETER,
        status=AnswerStatus.GROUNDED,
        headline=(
            f"{len(matches)} monitored "
            + " / ".join(f"{t.replace('_', ' ')}s" for t in resolution.water_types)
            + f"{scope}, each shown with its latest measured status and date."
            if listing
            else f"{len(matches)} monitored {plural}{scope} had {what} at the most "
            "recent measurement."
        ),
        sections=[{"kind": "list", "items": items}],
        citations=citations,
        limitations=[
            "Based on each water body's most recent measurement, dated per item; "
            "none is a present-tense statement.",
            "Water bodies where the parameter was not measured are excluded, not "
            "counted as compliant.",
        ],
        map_action=_map_action([m[0] for m in matches]),
    )


def _answer_compare(
    db: Session, tracer: _Tracer, question: str, resolution: Resolution
) -> WaterAnswer:
    if len(resolution.water_bodies) < 2:
        return WaterAnswer(
            question=question,
            intent=Intent.COMPARE,
            status=AnswerStatus.NO_EVIDENCE,
            headline=(
                "A comparison needs two water bodies, and "
                f"{len(resolution.water_bodies)} could be matched in the ingested data."
            ),
            limitations=[
                "Only water bodies present in ingested CPCB data can be compared.",
            ],
        )
    answer = _answer_status(db, tracer, question, resolution, Intent.COMPARE)
    answer.limitations.insert(
        0,
        "The two water bodies may have been sampled on different dates and for "
        "different parameters; compare dates before comparing values.",
    )
    return answer


def _answer_standards(db: Session, tracer: _Tracer, question: str) -> WaterAnswer:
    from app.rag.service import search as corpus_search

    hits = tracer.call(
        "RESEARCH", "search_corpus", corpus_search, db=db, query=question, limit=3
    )
    hits = [h for h in hits if h.document_id.startswith(("cpcb-", "oip-water"))] or []
    if not hits:
        return _no_evidence(question, Intent.STANDARDS)

    citations = [
        Citation(
            position=i + 1,
            kind="document",
            title=h.title,
            detail=h.text[:280] + ("…" if len(h.text) > 280 else ""),
            evidence_type="RETRIEVED",
            url=h.source_url,
            source=h.publication,
        )
        for i, h in enumerate(hits)
    ]
    return WaterAnswer(
        question=question,
        intent=Intent.STANDARDS,
        status=AnswerStatus.GROUNDED,
        headline="Retrieved from the reference criteria this platform applies.",
        sections=[
            {
                "kind": "passages",
                "items": [
                    {"title": h.title, "text": h.text, "cite": i + 1}
                    for i, h in enumerate(hits)
                ],
            }
        ],
        citations=citations,
        limitations=[
            "These are platform-authored summaries of the CPCB documents. Consult "
            "the linked originals before relying on them.",
        ],
    )


def _no_evidence(question: str, intent: Intent) -> WaterAnswer:
    return WaterAnswer(
        question=question,
        intent=intent,
        status=AnswerStatus.NO_EVIDENCE,
        headline=(
            "No record in the ingested data answers this question, so no answer is given."
        ),
        limitations=[
            "This assistant answers only from stored observations and the "
            "reference corpus. It does not estimate, and it does not fall back on "
            "a language model's own knowledge.",
            "Try naming a water body, district or state that appears in the "
            "ingested CPCB data, e.g. 'What is the latest status of Mithi River?'",
        ],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def answer(db: Session, question: str) -> dict:
    """Run the five-stage pipeline and return a serialised answer."""
    question = (question or "").strip()
    tracer = _Tracer()

    intent = tracer.call(
        "IDENTIFY", "classify_intent", classify_intent, question=question
    )
    resolution = tracer.call(
        "IDENTIFY", "resolve_entities", resolve_entities, db=db, question=question
    )

    has_body = bool(resolution.water_bodies)
    has_place = bool(resolution.districts or resolution.states or resolution.cities)
    wants_filter = bool(
        resolution.parameters
        or resolution.wants_polluted
        or resolution.wants_high_concern
        or resolution.wants_no_recent
    )

    if intent is Intent.STANDARDS and not has_body:
        result = _answer_standards(db, tracer, question)
    elif intent is Intent.COMPARE:
        result = _answer_compare(db, tracer, question, resolution)
    elif intent is Intent.NEARBY:
        result = _answer_nearby(db, tracer, question, resolution)
    elif (
        resolution.cities
        and not has_body
        and (wants_filter or resolution.water_types or resolution.wants_stations)
    ):
        result = _answer_city(db, tracer, question, resolution)
    elif intent is Intent.TREND and has_body:
        result = _answer_trend(db, tracer, question, resolution)
    elif has_body:
        result = _answer_status(
            db,
            tracer,
            question,
            resolution,
            intent if intent is not Intent.UNKNOWN else Intent.STATUS,
        )
    elif resolution.states and resolution.water_types and not resolution.districts:
        result = _answer_parameter_filter(db, tracer, question, resolution)
    elif has_place and wants_filter:
        if resolution.districts and not resolution.states:
            result = _answer_nearby(db, tracer, question, resolution)
        else:
            result = _answer_parameter_filter(db, tracer, question, resolution)
    elif wants_filter:
        result = _answer_parameter_filter(db, tracer, question, resolution)
    elif has_place and resolution.districts:
        result = _answer_nearby(db, tracer, question, resolution)
    else:
        result = _no_evidence(question, intent)

    tracer.call("REPORT", "assemble_answer", lambda: result.headline)
    result.resolution = resolution.describe()
    result.trace = tracer.calls
    payload = result.to_dict()
    payload["answered_at"] = datetime.now(UTC).isoformat()
    return payload
