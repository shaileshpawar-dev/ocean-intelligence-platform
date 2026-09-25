"""Deterministic water-body identity resolution from station metadata.

The problem
-----------
The CPCB extracts published on the National Water Data Portal ship a ``River``
column that is empty for every row sampled nationwide. The water body's name
is instead buried inside the station name, together with the sampling
position, the nearest landmark and the district::

    MITHI RIVER MAHIM BANDRA MUMBAI
    RIVER COOUM AT AMANJIKARAI
    GODAVARI AT NASIK D/S GADGEBABA MAHARAJ NAGAR NASHIK
    GROUND WATER NEAR BPMS H.S. SCHOOL SONARI TOWN DIST CHARAIDEO
    BORE WELL OF L & T LTD. PLOT NO. 144/146 SARKHEJ-BAVLA ROAD SANAND

So identity has to be parsed. This module does that with rules, not a
language model, for three reasons: the result must be reproducible across
runs, it must be auditable when it is wrong, and it must not cost an API call
per station. Every water body records which method named it and how confident
that method is, so a low-confidence grouping is visible in the UI rather than
presented as fact.

The rules, in order of confidence
---------------------------------
1. **source_field** (1.0) -- the source populated ``River`` or ``Tributary``.
   Trusted outright. Currently never fires for CPCB, but other providers do
   populate it and the branch is the reason adding them is cheap.
2. **station_name_parse** (0.75) -- the name contains an explicit water-type
   keyword: ``RIVER``, ``LAKE``, ``TANK``, ``BEEL``, ``CREEK``, ``DAM``.
3. **type_propagated** (0.6) -- the name carries no keyword, but the same
   normalised name appears elsewhere in the corpus *with* one. ``BRAHAMPUTRA
   RIVER AT BOGIBEEL BRIDGE`` establishes that ``BRAHMAPUTRA AT X`` is a
   river. Inference from the data itself, never a hardcoded river list.
4. **unclassified** (0.4) -- a name survives parsing but no type can be
   established. Typed ``OTHER`` and labelled as such. ``ERODE-2`` and
   ``GIDC DAHOD DAHOD`` genuinely do not identify a water body, and saying so
   is better than guessing.

Guarding against false merges
-----------------------------
Rivers cross state lines, so a river is keyed nationally by name. Lakes,
tanks, ponds and wells are local features whose names repeat constantly
across India, so those are keyed per state. Even for rivers, a candidate
station further than :data:`MAX_MERGE_KM` from an existing body's centroid
starts a new, state-qualified water body rather than dragging the centroid
across the subcontinent -- which is what stops the Amravati river in Tamil
Nadu from merging with the Amravati in Gujarat.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

from app.models.enums import WaterBodyType

# Two stations more than this far apart are not assumed to be the same water
# body even when their names match. Chosen to comfortably span a long Indian
# river's monitored reach while still separating same-named features in
# different parts of the country.
MAX_MERGE_KM = 500.0

# Water bodies keyed nationally; everything else is keyed per state.
NATIONAL_TYPES = frozenset(
    {WaterBodyType.RIVER, WaterBodyType.RIVER_STRETCH, WaterBodyType.ESTUARY}
)

CONFIDENCE = {
    "source_field": 1.0,
    # The source named a sub-basin, which can be coarser than the watercourse
    # actually sampled, so it is evidence but not as good as a river name.
    "source_sub_basin": 0.55,
    "station_name_parse": 0.75,
    "type_propagated": 0.6,
    "unclassified": 0.4,
}

# Values a source column uses for "no value here". CWC writes "-" in the
# Tributary column when the station is on the basin's main river.
_NULL_FIELD_TOKENS = frozenset({"", "-", "--", "---", "na", "n/a", "nil", "none", "."})

# ---------------------------------------------------------------------------
# Vocabulary
#
# Keywords are drawn from the station names actually published, including the
# regional terms that dominate some states: "beel" and "pukhuri" in Assam,
# "cheruvu" and "kunta" in Telugu-speaking areas, "kere" and "katte" in
# Karnataka, "talab" and "sagar" in the Hindi belt.
# ---------------------------------------------------------------------------
TYPE_KEYWORDS: tuple[tuple[str, WaterBodyType], ...] = (
    ("river", WaterBodyType.RIVER),
    ("nadi", WaterBodyType.RIVER),
    ("nadhi", WaterBodyType.RIVER),
    ("estuary", WaterBodyType.ESTUARY),
    ("backwater", WaterBodyType.ESTUARY),
    ("backwaters", WaterBodyType.ESTUARY),
    ("creek", WaterBodyType.CREEK),
    ("khadi", WaterBodyType.CREEK),
    ("lake", WaterBodyType.LAKE),
    ("beel", WaterBodyType.LAKE),
    ("cheruvu", WaterBodyType.LAKE),
    ("kere", WaterBodyType.LAKE),
    ("sarovar", WaterBodyType.LAKE),
    ("talab", WaterBodyType.LAKE),
    ("jheel", WaterBodyType.LAKE),
    ("pukhuri", WaterBodyType.POND),
    ("pond", WaterBodyType.POND),
    ("kunta", WaterBodyType.POND),
    ("kunte", WaterBodyType.POND),
    ("tank", WaterBodyType.POND),
    ("katte", WaterBodyType.POND),
    ("dam", WaterBodyType.RESERVOIR),
    ("reservoir", WaterBodyType.RESERVOIR),
    ("barrage", WaterBodyType.RESERVOIR),
    ("canal", WaterBodyType.CANAL),
    ("nahar", WaterBodyType.CANAL),
    ("nala", WaterBodyType.DRAIN),
    ("nalla", WaterBodyType.DRAIN),
    ("nallah", WaterBodyType.DRAIN),
    ("drain", WaterBodyType.DRAIN),
    ("sea", WaterBodyType.COASTAL),
    ("beach", WaterBodyType.COASTAL),
    ("coast", WaterBodyType.COASTAL),
    ("bay", WaterBodyType.COASTAL),
    ("harbour", WaterBodyType.COASTAL),
)

# Phrases that mark the station as sampling groundwater rather than a surface
# water body. ~200 of the 1,162 sampled stations are of this kind, and typing
# them as rivers would be straightforwardly wrong.
GROUNDWATER_PREFIXES = (
    "ground water",
    "groundwater",
    "bore well",
    "borewell",
    "bore-well",
    "tube well",
    "tubewell",
    "hand pump",
    "handpump",
    "well at",
    "well of",
    "well near",
    "dug well",
    "open well",
)

# Engineered assets, not natural water bodies. An overhead service tank is a
# municipal structure; grouping it with lakes because the word "tank" appears
# would put a water tower on a map of lakes.
INFRASTRUCTURE_PREFIXES = (
    "over head tank",
    "overhead tank",
    "o h tank",
    "water supply",
    "treatment plant",
    "stp ",
    "etp ",
    "pumping station",
)

# Tokens that introduce the *position* of sampling. Everything from the first
# one onward describes where on the water body the sample was taken, not
# which water body it is.
POSITION_MARKERS = (
    " at ",
    " near ",
    " nr ",
    " d/s ",
    " u/s ",
    " ds ",
    " us ",
    " before ",
    " after ",
    " from ",
    " on ",
    " in ",
    " opp ",
    " opposite ",
    " downstream ",
    " upstream ",
    " midstream",
    " mid stream",
    " mid-stream",
    " d/stream",
    " u/stream",
    " confl",
    # "after confluence" / "before confluence", the gauging shorthand both
    # agencies use: "Krishna A/c With Tungabhadra" is a position on the
    # Krishna, and reading it as a name made 31 one-station water bodies.
    " a/c ",
    " b/c ",
    " bridge",
    " ghat",
    " intake",
)

# Administrative and descriptive noise that can trail a water body's name.
TRAILING_NOISE = {
    "dist",
    "distt",
    "district",
    "taluk",
    "taluka",
    "tehsil",
    "village",
    "town",
    "city",
    "state",
    "block",
    "panchayat",
    "no",
    "pt",
    "point",
}


# Official renamings of Indian cities and districts. The CPCB extracts use a
# mix of old and new names ("Bangalore Urban", "Belgaum", "Mysore"), while
# people search with whichever they know. Each pair is a documented official
# rename, not a guess; nothing here maps one place onto a different place.
PLACE_ALIASES: dict[str, tuple[str, ...]] = {
    "BENGALURU": ("BANGALORE",),
    "BANGALORE": ("BENGALURU",),
    "MUMBAI": ("BOMBAY",),
    "BOMBAY": ("MUMBAI",),
    "CHENNAI": ("MADRAS",),
    "MADRAS": ("CHENNAI",),
    "KOLKATA": ("CALCUTTA",),
    "CALCUTTA": ("KOLKATA",),
    "BELAGAVI": ("BELGAUM",),
    "BELGAUM": ("BELAGAVI",),
    "MYSURU": ("MYSORE",),
    "MYSORE": ("MYSURU",),
    "SHIVAMOGGA": ("SHIMOGA",),
    "SHIMOGA": ("SHIVAMOGGA",),
    "KALABURAGI": ("GULBARGA",),
    "GULBARGA": ("KALABURAGI",),
    "VIJAYAPURA": ("BIJAPUR",),
    "BIJAPUR": ("VIJAYAPURA",),
    "BALLARI": ("BELLARY",),
    "BELLARY": ("BALLARI",),
    "TUMAKURU": ("TUMKUR",),
    "TUMKUR": ("TUMAKURU",),
    "GURUGRAM": ("GURGAON",),
    "GURGAON": ("GURUGRAM",),
    "PRAYAGRAJ": ("ALLAHABAD",),
    "ALLAHABAD": ("PRAYAGRAJ",),
    "PUDUCHERRY": ("PONDICHERRY",),
    "PONDICHERRY": ("PUDUCHERRY",),
    "THIRUVANANTHAPURAM": ("TRIVANDRUM",),
    "TRIVANDRUM": ("THIRUVANANTHAPURAM",),
    "KOCHI": ("COCHIN",),
    "COCHIN": ("KOCHI",),
    "VADODARA": ("BARODA",),
    "BARODA": ("VADODARA",),
    "PUNE": ("POONA",),
    "POONA": ("PUNE",),
}


# Spelling variants of the same river as they occur in the published station
# names. Each pair names one watercourse spelled two ways -- not two rivers
# that happen to be similar -- and the canonical form is the one most widely
# used in official Indian sources. Kept deliberately short: an entry here
# merges records, so it has to be certain.
CANONICAL_SPELLINGS: dict[str, str] = {
    "BRAHAMPUTRA": "BRAHMAPUTRA",
    "BRAHMPUTRA": "BRAHMAPUTRA",
    "GODAVRI": "GODAVARI",
    "KAVERI": "CAUVERY",
    "MAHANADHI": "MAHANADI",
    "HOOGHLY": "HUGLI",
    "SABARAMATI": "SABARMATI",
    "NARMADHA": "NARMADA",
    "TAPTI": "TAPI",
    "SATLUJ": "SUTLEJ",
    "SUTLUJ": "SUTLEJ",
    # Both pairs were found by geometry QA: the two spellings had matched the
    # same OpenStreetMap ways, which is as direct as evidence gets that they
    # are one river. The commoner spelling in the published data wins
    # (Subarnarekha 24 stations to 3; Kosi 9 to 4).
    "SWARNREKHA": "SUBARNAREKHA",
    "KOSHI": "KOSI",
}

# Drains may share a name with the river they join ("Mithi Nallah", "Mithi
# River"). Within this distance a drain with the same name as a river is the
# same watercourse under a local label, and its stations join the river.
DRAIN_TO_RIVER_KM = 25.0

# Two same-named river fragments are one river when their nearest monitoring
# stations are this close. CPCB stations on the Ganga, Yamuna and Godavari are
# typically 30-120 km apart across state lines; distinct same-named rivers in
# different parts of India are hundreds of kilometres apart.
RIVER_LINK_KM = 150.0


def canonical_core(normalized: str) -> str:
    """Rewrite known spelling variants inside a normalised name."""
    if not normalized:
        return normalized
    return " ".join(CANONICAL_SPELLINGS.get(t, t) for t in normalized.split())


def expand_place_aliases(text: str) -> str:
    """Append the official alternative name of any place mentioned.

    Operates on normalised (upper-case) text and only ever adds words, so a
    question that already uses the source's spelling is unchanged.
    """
    padded = f" {text} "
    extra = [
        alt
        for name, alts in PLACE_ALIASES.items()
        if f" {name} " in padded
        for alt in alts
    ]
    return f"{text} {' '.join(extra)}".strip() if extra else text


def _strip_accents(text: str) -> str:
    """Fold accented characters to ASCII for stable matching."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalise_name(name: str) -> str:
    """Canonical form used as the matching key.

    Upper-cased, accent-folded, punctuation removed, whitespace collapsed.
    Deliberately *not* stemmed: ``MITHI`` and ``MITHIA`` are different rivers.
    """
    text = _strip_accents(str(name or "")).upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify(text: str) -> str:
    """URL-safe slug for routes such as ``/app/water/mithi-river``."""
    slug = _strip_accents(str(text or "")).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return re.sub(r"-{2,}", "-", slug) or "unnamed"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


@dataclass(slots=True)
class MatchResult:
    """The water body a station was resolved to."""

    name: str
    """Display name, title-cased, e.g. ``Mithi River``."""

    normalized_name: str
    water_type: WaterBodyType
    method: str
    confidence: float
    notes: list[str] = field(default_factory=list)
    position: str | None = None
    """Where on the water body the sample was taken ("At Nasik D/S ..."),
    kept on the station. Never allowed to become part of the body's name."""

    aliases: list[str] = field(default_factory=list)
    """Other spellings seen for this water body, e.g. before canonicalisation."""

    @property
    def is_identified(self) -> bool:
        """False when parsing produced no usable water-body name."""
        return bool(self.normalized_name) and self.method != "unidentified"


def _title(text: str) -> str:
    """Title-case a parsed name without mangling short connectors."""
    small = {"of", "at", "on", "the", "and"}
    words = text.lower().split()
    out = [
        w.upper()
        if len(w) <= 2 and w.isalpha() and w not in small
        else (w if w in small and i else w.capitalize())
        for i, w in enumerate(words)
    ]
    return " ".join(out)


def _cut_at_position_marker(text: str) -> str:
    """Return the part of the name before the first position marker.

    Matching is done on a lower-cased copy while the slice is taken from the
    original, because station names are published in upper case and the
    markers are written in lower case. Comparing the two directly silently
    matches nothing, which lets the whole sampling position leak into the
    water body's name.
    """
    padded = f" {text} "
    probe = padded.lower()
    cut = len(padded)
    for marker in POSITION_MARKERS:
        idx = probe.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return padded[:cut].strip()


_LEADING_POSITION = re.compile(
    r"^(?:at|near|nr|from|of|in|on|the)\b[\s.,-]*", re.IGNORECASE
)


def _strip_leading_position(text: str) -> str:
    """Drop a position word left at the start of a parsed fragment.

    Removing a leading marker such as ``BORE WELL`` from
    ``BORE WELL AT WAHEGAON`` leaves ``AT WAHEGAON``. The position cutter
    cannot help here -- the marker is at index 0, so there is nothing before
    it to keep -- so the stranded preposition is stripped directly.
    """
    previous = None
    while previous != text:
        previous = text
        text = _LEADING_POSITION.sub("", text).strip(" .,-")
    return text


def _strip_trailing_noise(tokens: list[str]) -> list[str]:
    """Drop administrative filler from the end of a parsed name."""
    while tokens and tokens[-1].lower().strip(".,;:-()") in TRAILING_NOISE:
        tokens.pop()
    return tokens


def parse_station_name(station_name: str) -> MatchResult:
    """Resolve a water body from a station name alone.

    This is the branch that does the real work, because the CPCB ``River``
    column is empty. It never raises: an unparseable name yields an
    ``unidentified`` result that the caller records rather than discards.
    """
    raw = re.sub(r"\s+", " ", str(station_name or "").strip())
    # A leading article is not part of any name: "THE RIVER ASHWANI AT ..."
    # otherwise parsed as a river called "The".
    raw = re.sub(r"^(the)\s+", "", raw, flags=re.IGNORECASE)
    if not raw:
        return MatchResult("", "", WaterBodyType.OTHER, "unidentified", 0.0)

    lowered = raw.lower()

    # -- Groundwater -------------------------------------------------------
    # The water body is the aquifer sampled at a locality. Naming it after
    # the locality keeps every well in one town together, which is the most
    # useful grouping the data supports.
    for prefix in GROUNDWATER_PREFIXES:
        if lowered.startswith(prefix):
            remainder = _strip_leading_position(raw[len(prefix) :].strip(" .,-"))
            locality = _cut_at_position_marker(remainder) or remainder
            locality = " ".join(_strip_trailing_noise(locality.split()))
            if not locality:
                # e.g. "GROUND WATER AT (JORHAT ASSAM)" once brackets go.
                locality = re.sub(r"[()]", " ", remainder).strip()
                locality = " ".join(_strip_trailing_noise(locality.split()[:3]))
            label = f"Groundwater — {_title(locality)}" if locality else "Groundwater"
            return MatchResult(
                name=label,
                normalized_name=normalise_name(f"GROUNDWATER {locality}"),
                water_type=WaterBodyType.GROUNDWATER,
                method="station_name_parse",
                confidence=CONFIDENCE["station_name_parse"],
                notes=["Groundwater sampling point, not a surface water body."],
            )

    # The same marker can also trail the name -- "PATAN BOREWELL", "WELL NO 3
    # KADI" -- so a prefix test alone misses them.
    if re.search(
        r"\b(bore\s?well|tube\s?well|hand\s?pump|dug well|open well)\b", lowered
    ):
        locality = _cut_at_position_marker(
            re.sub(
                r"\b(bore\s?well|tube\s?well|hand\s?pump|dug well|open well)\b",
                " ",
                lowered,
            )
        )
        locality = " ".join(_strip_trailing_noise(locality.split()))
        label = f"Groundwater — {_title(locality)}" if locality else "Groundwater"
        return MatchResult(
            name=label,
            normalized_name=normalise_name(f"GROUNDWATER {locality}"),
            water_type=WaterBodyType.GROUNDWATER,
            method="station_name_parse",
            confidence=CONFIDENCE["station_name_parse"],
            notes=["Groundwater sampling point, not a surface water body."],
        )

    # -- Municipal infrastructure -----------------------------------------
    for prefix in INFRASTRUCTURE_PREFIXES:
        if lowered.startswith(prefix):
            return MatchResult(
                name=_title(_cut_at_position_marker(raw)) or raw.title(),
                normalized_name=normalise_name(_cut_at_position_marker(raw) or raw),
                water_type=WaterBodyType.OTHER,
                method="station_name_parse",
                confidence=CONFIDENCE["unclassified"],
                notes=["Engineered water-supply asset, not a natural water body."],
            )

    # -- Generic type prefix, e.g. "SEA WATER AT JUHU BEACH" ---------------
    # Here the type keyword leads and the identifying place name follows the
    # position marker, which is the opposite of the usual "<name> RIVER AT
    # <place>" order. Without this branch every coastal station in Mumbai
    # collapses into a single water body literally called "Sea Water".
    generic = re.match(
        r"^(sea|lake|river|creek|pond|tank|canal|estuary|backwater)"
        r"\s+water\b(.*)$",
        lowered,
        re.IGNORECASE,
    )
    if generic:
        keyword = generic.group(1).lower()
        wtype = next(t for k, t in TYPE_KEYWORDS if k == keyword)
        locality = _strip_leading_position(generic.group(2).strip(" .,-"))
        locality = " ".join(_strip_trailing_noise(locality.split())[:5])
        label = (
            f"{keyword.capitalize()} Water — {_title(locality)}"
            if locality
            else f"{keyword.capitalize()} Water"
        )
        return MatchResult(
            name=label,
            normalized_name=normalise_name(f"{keyword} water {locality}"),
            water_type=wtype,
            method="station_name_parse",
            confidence=CONFIDENCE["station_name_parse"],
            notes=[
                "Named from the sampling locality; the source gives the water "
                "body only as a generic type."
            ],
        )

    # -- "... ON RIVER X" --------------------------------------------------
    # "WATER INTAKE POINT FOR BANKURA TOWN ON RIVER DWARAKESHWAR BANKURA"
    # names its river only at the end.
    tail = re.search(r"\bon river\s+([a-z][a-z .'-]{2,})", lowered)
    if tail:
        name = " ".join(_strip_trailing_noise(tail.group(1).split()))
        if name:
            return MatchResult(
                name=f"{_title(name)} River",
                normalized_name=normalise_name(name),
                water_type=WaterBodyType.RIVER,
                method="station_name_parse",
                confidence=CONFIDENCE["station_name_parse"],
            )

    # -- Leading "RIVER X" -------------------------------------------------
    head = _cut_at_position_marker(raw)
    head = re.sub(r"\(.*?\)", " ", head)
    head = re.sub(r"\s+", " ", head).strip(" .,-")

    leading = re.match(r"^(river|lake|dam|canal|creek)\s+(.+)$", head, re.IGNORECASE)
    if leading:
        kind = leading.group(1).lower()
        name = " ".join(_strip_trailing_noise(leading.group(2).split()))
        wtype = next(t for k, t in TYPE_KEYWORDS if k == kind)
        if name:
            display = _title(name)
            if kind not in display.lower():
                display = f"{display} {kind.capitalize()}"
            return MatchResult(
                name=display,
                normalized_name=normalise_name(name),
                water_type=wtype,
                method="station_name_parse",
                confidence=CONFIDENCE["station_name_parse"],
            )

    # -- Trailing / embedded type keyword ---------------------------------
    tokens = _strip_trailing_noise(head.split())
    if not tokens:
        return MatchResult("", "", WaterBodyType.OTHER, "unidentified", 0.0)

    lowered_tokens = [t.lower().strip(".,") for t in tokens]
    for index in range(len(lowered_tokens) - 1, -1, -1):
        for keyword, wtype in TYPE_KEYWORDS:
            if lowered_tokens[index] == keyword:
                name_tokens = tokens[: index + 1]
                if len(name_tokens) == 1:
                    # The keyword alone, e.g. a bare "LAKE". Not a name.
                    continue
                display = _title(" ".join(name_tokens))
                return MatchResult(
                    name=display,
                    normalized_name=normalise_name(" ".join(name_tokens[:index])),
                    water_type=wtype,
                    method="station_name_parse",
                    confidence=CONFIDENCE["station_name_parse"],
                )

    # -- No keyword: a bare name such as "GODAVARI" ------------------------
    # Typed OTHER here. A later propagation pass may upgrade it if the same
    # name appears elsewhere with an explicit keyword.
    name_tokens = tokens[:4]
    display = _title(" ".join(name_tokens))
    return MatchResult(
        name=display,
        normalized_name=normalise_name(" ".join(name_tokens)),
        water_type=WaterBodyType.OTHER,
        method="unclassified",
        confidence=CONFIDENCE["unclassified"],
        notes=["Water-body type not stated by the source and not inferable."],
    )


def _source_field(text: str | None) -> str | None:
    """A source column value, or None when the column says "not applicable".

    CWC writes ``-`` for "this station is not on a tributary", which is
    information, not a name.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if cleaned.lower() in _NULL_FIELD_TOKENS:
        return None
    return cleaned


def _tidy_watercourse_label(text: str) -> str:
    """Strip the bookkeeping the sub-basin column carries.

    ``Bhagirathi-II (WB)*`` is the source's label for a numbered sub-basin
    reach in West Bengal, not the name of a river. The suffixes go; the
    original is kept as an alias by the caller.
    """
    cleaned = re.sub(r"\s*\([^)]*\)", "", text)  # "(WB)"
    cleaned = cleaned.replace("*", "")
    # A trailing segment number: "Bhagirathi-II", "Yamuna - I".
    cleaned = re.sub(r"\s*[-\u2013]\s*(?:[IVXLC]+|\d+)\s*$", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" -\u2013,")


def _as_river(text: str, *, method: str) -> MatchResult:
    """Build a river MatchResult from a source column value."""
    tidied = _tidy_watercourse_label(text) or text
    display = _title(tidied)
    if "river" not in display.lower():
        display = f"{display} River"
    # The alias keeps the source's spelling exactly as published.
    aliases = [text] if normalise_name(tidied) != normalise_name(text) else []
    return MatchResult(
        name=display,
        normalized_name=normalise_name(tidied),
        water_type=WaterBodyType.RIVER,
        method=method,
        confidence=CONFIDENCE[method],
        aliases=aliases,
    )


def resolve(
    station_name: str,
    *,
    river: str | None = None,
    tributary: str | None = None,
    basin: str | None = None,
) -> MatchResult:
    """Resolve a water body from the source's own columns, then the label.

    The columns are not all the same kind of thing, which took a QA pass on
    real data to establish:

    * When ``River`` differs from ``Basin`` -- every Odisha row, where the
      basin is "Brahmani and Baitarni" and the river is "Baitarani" -- the
      ``River`` column names a watercourse and is trusted.
    * When ``River`` repeats ``Basin`` -- 72% of the CWC rows sampled, and
      every row for Uttar Pradesh -- it is a **basin label**. Then an empty
      ``Tributary`` means the station is on that basin's main river, and a
      populated one names the sub-basin. Reading the basin label as the water
      body is what put every Sikkim station on the Brahmaputra mainstem, up
      to 264 km from the Teesta they actually sample.
    * A station whose own label **names one of the columns** settles it:
      "Tapi at Sarangkheda" stands on the Tapi and "Purna at Gopalkheda" on
      the Purna, though both rows carry the same pair.
    * Failing that, the **more specific name wins**: a populated
      ``Tributary`` beats the river it joins, because the finer name is both
      likelier to be the stream sampled and less likely to attract the wrong
      geometry.
    * A station whose own label names a **lake, tank, reservoir, pond or
      well** is that water body, whatever basin it drains to. Gurudongmar
      Lake is in the Brahmaputra basin; it is not the Brahmaputra.

    A sub-basin name is recorded at lower confidence than a river name,
    because the sub-basin can still be coarser than the stream sampled: a
    station at Ujjain is in the Yamuna sub-basin but stands on the Shipra,
    which the source never names.
    """
    river_value = _source_field(river)
    basin_value = _source_field(basin)
    tributary_value = _source_field(tributary)

    parsed = finalise(station_name, parse_station_name(station_name))

    # A still water body named in the label outranks any drainage column.
    if parsed.is_identified and parsed.water_type not in {
        WaterBodyType.RIVER,
        WaterBodyType.OTHER,
    }:
        return parsed

    basin_key = normalise_name(basin_value or "")
    river_key = normalise_name(river_value or "")
    tributary_key = normalise_name(tributary_value or "")
    river_is_basin_label = bool(basin_key) and river_key == basin_key

    label_key = f" {normalise_name(station_name)} "
    parsed_key = parsed.normalized_name if parsed.is_identified else ""

    def named_in_label(key: str) -> bool:
        return bool(key) and (parsed_key == key or f" {key} " in label_key)

    # The label naming a column outranks specificity: the row for "Tapi at
    # Sarangkheda" also carries Tributary=Purna, but the station says which
    # watercourse it stands on. The finer name is tested first.
    if tributary_value and named_in_label(tributary_key):
        return _as_river(tributary_value, method="source_field")
    if river_value and named_in_label(river_key):
        return _as_river(river_value, method="source_field")

    # Most specific first. A tributary that merely repeats the river or the
    # basin adds nothing.
    if tributary_value and tributary_key not in {river_key, basin_key}:
        method = "source_sub_basin" if river_is_basin_label else "source_field"
        return _as_river(tributary_value, method=method)

    if river_value:
        return _as_river(river_value, method="source_field")

    return parsed


_TYPE_WORDS_UPPER = frozenset({k.upper() for k, _ in TYPE_KEYWORDS} | {"WATER"})


def sampling_descriptor(station_name: str, result: MatchResult) -> str | None:
    """The part of a station name that describes *where* it samples.

    ``GODAVARI AT NASIK D/S GADGEBABA MAHARAJ NAGAR NASHIK`` names the
    Godavari and then a position on it. The position is information about the
    station, so it is returned for the station record rather than discarded
    -- and it is never allowed to split the water body.

    Matching is done token by token on normalised forms but the text is cut
    from the original tokens, so ``D/S`` survives as ``D/S`` rather than
    becoming ``D S``.
    """
    core = result.normalized_name.split()
    raw_tokens = str(station_name or "").split()
    norm_tokens = [normalise_name(t) for t in raw_tokens]
    if not core or not raw_tokens:
        return None

    # A multi-word token such as "D/S" normalises to "D S"; compare on the
    # first word of each so positions stay aligned with the raw tokens.
    heads = [t.split()[0] if t else "" for t in norm_tokens]
    for i in range(len(heads) - len(core) + 1):
        if heads[i : i + len(core)] == core:
            end = i + len(core)
            while end < len(heads) and heads[end] in _TYPE_WORDS_UPPER:
                end += 1
            descriptor = " ".join(raw_tokens[end:]).strip(" ,.-")
            if not descriptor:
                return None
            # Title-case words, keep position abbreviations upper-case.
            words = [
                w.upper() if "/" in w or w.upper() in {"D/S", "U/S", "NH"} else w.title()
                for w in descriptor.split()
            ]
            return " ".join(words)
    return None


def finalise(station_name: str, result: MatchResult) -> MatchResult:
    """Attach the sampling descriptor, then apply canonical spellings.

    The descriptor is taken first, against the name as published, because a
    station labelled ``BRAHAMPUTRA RIVER AT BOGIBEEL`` does not contain the
    canonical spelling ``BRAHMAPUTRA``.
    """
    if result.position is None:
        result.position = sampling_descriptor(station_name, result)

    if not result.normalized_name:
        return result

    canonical = canonical_core(result.normalized_name)
    if canonical == result.normalized_name:
        return result

    original = result.name
    renamed = []
    for word in result.name.split():
        variant = normalise_name(word)
        renamed.append(
            CANONICAL_SPELLINGS[variant].title()
            if variant in CANONICAL_SPELLINGS
            else word
        )
    result.name = " ".join(renamed)
    if original != result.name and original not in result.aliases:
        result.aliases.append(original)
    result.normalized_name = canonical
    return result


def propagate_types(results: list[MatchResult]) -> dict[str, WaterBodyType]:
    """Learn water-body types from the corpus itself.

    Builds a map from normalised name to type using only results that carried
    an explicit keyword. ``BRAHAMPUTRA RIVER AT BOGIBEEL BRIDGE`` teaches the
    platform that ``BRAHMAPUTRA`` is a river, so the many bare ``BRAHMAPUTRA
    AT <place>`` stations can be typed from evidence in the data rather than
    from a hardcoded list of Indian rivers.

    A name that appears with conflicting types is left out: ambiguity is not
    resolved by majority vote, because the tie-break would be arbitrary.
    """
    votes: dict[str, set[WaterBodyType]] = {}
    for result in results:
        if result.method == "station_name_parse" and result.normalized_name:
            votes.setdefault(result.normalized_name, set()).add(result.water_type)

    return {
        name: next(iter(types))
        for name, types in votes.items()
        if len(types) == 1 and next(iter(types)) is not WaterBodyType.OTHER
    }


def apply_propagation(
    result: MatchResult, learned: dict[str, WaterBodyType]
) -> MatchResult:
    """Upgrade an unclassified result using a learned type, if one exists."""
    if result.method != "unclassified" or not result.normalized_name:
        return result

    wtype = learned.get(result.normalized_name)
    if wtype is None:
        return result

    suffix = {
        WaterBodyType.RIVER: "River",
        WaterBodyType.LAKE: "Lake",
        WaterBodyType.POND: "Tank",
        WaterBodyType.RESERVOIR: "Reservoir",
        WaterBodyType.CREEK: "Creek",
        WaterBodyType.CANAL: "Canal",
        WaterBodyType.DRAIN: "Drain",
        WaterBodyType.COASTAL: "Coast",
        WaterBodyType.ESTUARY: "Estuary",
    }.get(wtype)

    name = result.name
    if suffix and suffix.lower() not in name.lower():
        name = f"{name} {suffix}"

    return MatchResult(
        name=name,
        normalized_name=result.normalized_name,
        water_type=wtype,
        method="type_propagated",
        confidence=CONFIDENCE["type_propagated"],
        notes=[
            "Type inferred from other stations on the same named water body "
            "elsewhere in the source data, not stated for this station."
        ],
    )


def merge_key(result: MatchResult, state_code: str | None) -> tuple[str, str, str]:
    """Key under which stations are grouped into one water body.

    Rivers are keyed nationally because they cross state lines; local
    features are keyed per state because their names repeat all over India.
    """
    scope = "" if result.water_type in NATIONAL_TYPES else (state_code or "")
    return (result.normalized_name, str(result.water_type), scope)


def is_plausible_merge(
    lat: float | None,
    lon: float | None,
    centroid_lat: float | None,
    centroid_lon: float | None,
) -> bool:
    """Whether a station is close enough to join an existing water body.

    Missing coordinates return ``True``: the name matched, and refusing the
    merge purely because a position is absent would fragment a real river
    into one water body per ungeocoded station.
    """
    if None in (lat, lon, centroid_lat, centroid_lon):
        return True
    assert lat is not None and lon is not None
    assert centroid_lat is not None and centroid_lon is not None
    return haversine_km(lat, lon, centroid_lat, centroid_lon) <= MAX_MERGE_KM
