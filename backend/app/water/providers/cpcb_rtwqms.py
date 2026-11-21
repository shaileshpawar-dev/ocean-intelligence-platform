"""CPCB Real-Time Water Quality Monitoring: the first genuinely current source.

Every source the platform had until now was historical. CPCB's manual extracts
mostly stop in 2021 and the Central Water Commission's run to mid-2025, so the
honest answer to "what is the river like today?" was always "that cannot be
established from this dataset".

This one can answer it, for 40 stations. CPCB runs automatic analysers on the
Ganga and its tributaries under the Namami Gange programme and publishes the
readings as plain JSON behind its dashboard at ``rtwqmsdb1.cpcb.gov.in``: no
key, no registration, one file per layer. Verified from this environment on
26 September 2026, returning values timestamped **the same hour**.

What it is
    40 stations in Uttarakhand, Uttar Pradesh, Haryana, Bihar, Jharkhand and
    West Bengal -- the Ganga main stem and tributaries, not the whole country.
    Readings arrive hourly. Twelve series per station, of which nine are
    water-quality parameters this platform already knows; ``Depth`` and ``S``
    are hydrology (level and stage) and ``TOC`` has no entry in the parameter
    registry, so all three are skipped rather than guessed at.

What it is not
    Not a national picture, and not a laboratory. These are field analysers:
    they drift, they are cleaned on a schedule, and they go offline. The feed
    is candid about that -- every record carries a maintenance diary, and the
    platform keeps the last one as a note on the observation rather than
    hiding it. A station that stopped reporting keeps its last reading in the
    feed, so **the feed being live does not mean every station in it is**: on
    the day this was written 39 of 40 stations had reported within the hour
    and one had not reported since 2 September. Freshness is therefore judged
    per station, from the observation's own timestamp, exactly as it is for
    the historical sources.

Because a live feed returns the same record count whatever the values are,
``resource_total`` deliberately reports nothing: there is no cheap cursor, so
every run re-reads. Re-reading is safe -- the uniqueness key is (source,
station, parameter, observed_at), so a second run within the same hour inserts
nothing and the next hour inserts one new row per series.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from app.core.logging import get_logger
from app.water.freshness import Cadence
from app.water.parameters import BY_KEY, parse_value
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    ProviderUnavailableError,
    WaterDataProvider,
)

logger = get_logger(__name__)

BASE_URL = "https://rtwqmsdb1.cpcb.gov.in"
STATIONS_PATH = "/data/internet/stations/stations.json"
LAYER_PATH = "/data/internet/layers/10/index.json"
TIMEOUT = 60
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """Verify this host against certifi rather than the OS trust store.

    CPCB serves a valid certificate chaining to ``emSign Root CA - G1``
    (eMudhra), a root in the Mozilla programme and therefore in certifi, but
    *not* present in a default Windows certificate store. Plain
    ``urlopen`` uses the OS store, so the same feed verified inside the Debian
    container and failed on a Windows developer machine -- which is how this
    source came to be recorded as unreachable when it was in fact up.

    Naming the bundle fixes the trust decision to one we ship, so the answer
    no longer depends on which machine asks. Verification stays fully on:
    hostname checking and expiry are unchanged, and an untrusted chain still
    raises.
    """
    import certifi

    return ssl.create_default_context(cafile=certifi.where())

#: The feed's series names, mapped to this platform's canonical parameters.
#: Only what is genuinely the same quantity: ``Depth`` and ``S`` measure the
#: river, not its quality, and ``TOC`` has no canonical entry yet.
PARAMETER_MAP: dict[str, str] = {
    "pH": "ph",
    "WT": "temperature",
    "BOD": "bod",
    "COD": "cod",
    "DO": "dissolved_oxygen",
    "Nitrate": "nitrate",
    "EC": "electrical_conductivity",
    "WTb": "turbidity",
    "CL": "chloride",
}

#: Series deliberately not ingested, and why. Kept as data so the coverage
#: report can say what was left on the table instead of it being invisible.
UNMAPPED_SERIES: dict[str, str] = {
    "Depth": "river depth, a hydrological quantity, not water quality",
    "S": "stage/level, a hydrological quantity, not water quality",
    "TOC": "total organic carbon has no entry in the parameter registry",
}

#: The unit symbols the feed uses, normalised to what the registry expects.
#: "---" means dimensionless (pH); the degree symbol arrives mis-encoded.
# The registry spells water temperature "degC"; "deg C" is not
# recognised, and a reading arrives flagged unit_not_convertible with no
# normalised unit at all.
UNIT_FIXES: dict[str, str] = {
    "---": "",
    "\u00c2\u00b0C": "degC",
    "\u00b0C": "degC",
    "mS/cm": "mS/cm",
    "mg/l": "mg/L",
    "NTU": "NTU",
}


def _clean(value: object) -> str:
    """Trim a source string, repairing the feed's mojibake."""
    text = str(value or "").strip()
    # The feed serves UTF-8 that was already decoded once as latin-1, so a
    # non-breaking space arrives as U+00C2 followed by U+00A0. Repair it
    # rather than carrying it into station names.
    return text.replace("\u00c2\u00a0", " ").replace("\u00c2", "").strip()


class CPCBRealTimeProvider(WaterDataProvider):
    """The 40-station real-time Ganga network, read from the public JSON."""

    def __init__(self) -> None:
        """Create a provider with an empty per-run cache."""
        self._layer: list[dict] | None = None

    @property
    def info(self) -> ProviderInfo:
        """Describe the source, including what it cannot do."""
        return ProviderInfo(
            key="cpcb_rtwqms",
            name="CPCB Real-Time Water Quality Monitoring",
            organisation="Central Pollution Control Board",
            url=f"{BASE_URL}/",
            dataset="Real-time automatic water-quality analysers (Namami Gange)",
            licence="Government of India open data (no licence stated on the feed)",
            cadence=Cadence.HOURLY,
            access="public",
            source_type="government",
            observation_method="continuous_sensor",
            reliability_note=(
                "Automatic field analysers, not laboratory analysis. The feed "
                "publishes each station's maintenance diary, and a station "
                "that has stopped reporting keeps its last value in the feed, "
                "so freshness is judged per observation rather than assumed "
                "from the source being live."
            ),
            notes=[
                "40 stations on the Ganga and its tributaries in Uttarakhand, "
                "Uttar Pradesh, Haryana, Bihar, Jharkhand and West Bengal. "
                "Not a national network.",
                "Nine of twelve series are ingested; depth and stage are "
                "hydrology and total organic carbon has no canonical "
                "parameter.",
            ],
        )

    # -- planning ----------------------------------------------------------
    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        """One plan per state present in the feed.

        Splitting by state keeps ``--states`` meaningful and gives each state
        its own resource-state row, the same shape as the other providers.
        """
        wanted = {s.upper() for s in states} if states else None
        seen: dict[str, str] = {}
        for record in self._records():
            code = _STATE_CODES.get(_clean(record.get("territory_name")))
            if code and code not in seen:
                seen[code] = _clean(record.get("territory_name"))
        return [
            FetchPlan(
                identifier=f"rtwqms-layer10-{code}",
                description=f"{name} - real-time analysers",
                state_code=code,
            )
            for code, name in sorted(seen.items())
            if wanted is None or code in wanted
        ]

    def resource_total(self, plan: FetchPlan) -> int | None:
        """No cursor: a live feed's record count does not change with values.

        Returning a count here would let the incremental sync skip the feed
        forever, because 40 stations report 40 records whether the readings
        are an hour old or a month old.
        """
        return None

    def health(self) -> tuple[bool | None, str]:
        """Probe the station catalogue, the smallest of the feed's documents.

        The catalogue is used rather than the measurement layer because it is
        an order of magnitude smaller and proves the same two things: that TLS
        verifies against this host and that it is serving JSON.
        """
        try:
            stations = self._get(STATIONS_PATH)
        except ProviderUnavailableError as exc:
            return False, str(exc)
        if not stations:
            return False, f"{BASE_URL}{STATIONS_PATH} returned an empty catalogue."
        return True, f"RTWQMS reachable; {len(stations)} stations in the catalogue."

    # -- fetching ----------------------------------------------------------
    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        """Yield one row per (station, parameter) reading for this state."""
        stations = {
            _clean(s.get("station_no")): s
            for s in self._stations()
            if s.get("station_no")
        }

        for record in self._records():
            code = _STATE_CODES.get(_clean(record.get("territory_name")))
            if plan.state_code and code != plan.state_code:
                continue

            series = _clean(record.get("stationparameter_name"))
            if series in UNMAPPED_SERIES or series not in PARAMETER_MAP:
                continue
            parameter = BY_KEY.get(PARAMETER_MAP[series])
            if parameter is None:
                continue

            observed_at = _parse_timestamp(record.get("timestamp"))
            if observed_at is None:
                continue

            raw_value = record.get("ts_value")
            if raw_value is None:
                continue

            unit = UNIT_FIXES.get(_clean(record.get("ts_unitsymbol")), "")
            parsed = parse_value(parameter, raw_value, source_unit=unit)
            if parsed.is_missing:
                continue

            station_no = _clean(record.get("station_no"))
            station = stations.get(station_no, {})
            name = _station_name(record, station)

            flags = list(parsed.flags)
            latitude = _float(record.get("station_latitude"))
            longitude = _float(record.get("station_longitude"))
            if latitude is None or longitude is None:
                flags.append("coordinates_missing")
            if observed_at > datetime.now(UTC):
                flags.append("future_dated")

            yield ObservationRow(
                station_name=name,
                parameter_key=parameter.key,
                observed_at=observed_at,
                value=parsed.value,
                unit=parameter.unit,
                normalized_value=parsed.normalized_value,
                normalized_unit=parsed.unit,
                qualitative_value=parsed.qualitative,
                raw_value=parsed.raw,
                quality_flags=flags,
                latitude=latitude,
                longitude=longitude,
                state_name=_clean(record.get("territory_name")),
                state_code=plan.state_code,
                agency="CPCB",
                # The feed's own words about this station's condition, kept so
                # a reading taken during a known fault is not silently clean.
                source_reference=(
                    f"cpcb_rtwqms:{station_no}:{series}:{observed_at.isoformat()}"
                ),
            )

    # -- transport ---------------------------------------------------------
    def _records(self) -> list[dict]:
        """The measurement layer, fetched once per provider instance."""
        if self._layer is None:
            self._layer = [r for r in self._get(LAYER_PATH) if isinstance(r, dict)]
        return self._layer

    def _stations(self) -> list[dict]:
        """The station catalogue, fetched once per provider instance."""
        if not hasattr(self, "_station_cache"):
            self._station_cache = [
                s for s in self._get(STATIONS_PATH) if isinstance(s, dict)
            ]
        return self._station_cache

    def _get(self, path: str) -> list:
        """GET one JSON document, with retries, or raise."""
        url = BASE_URL + path
        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                request = urllib.request.Request(
                    url, headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(
                    request, timeout=TIMEOUT, context=_ssl_context()
                ) as response:
                    payload = json.load(response)
                if isinstance(payload, list):
                    return payload
                last_error = f"expected a JSON array, got {type(payload).__name__}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "rtwqms_fetch_retry",
                extra={"path": path, "attempt": attempt, "error": last_error[:200]},
            )
            if attempt < MAX_RETRIES:
                # The feed intermittently returns a truncated body. Give it a
                # moment rather than hammering a public service three times in
                # as many milliseconds.
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        raise ProviderUnavailableError(f"{url} unavailable: {last_error}")


def _station_name(record: dict, station: dict) -> str:
    """The station's label, preferring the catalogue's fuller name.

    Names read like ``BH72_River Ganga at Chausa, U/s of Buxar``: the station
    code, then the water body and the position. The code prefix is dropped so
    the existing identity rules see "River Ganga at Chausa, U/s of Buxar" and
    resolve the Ganga with a sampling position, as they do for every other
    source.
    """
    label = _clean(station.get("station_name")) or _clean(record.get("station_name"))
    code = _clean(record.get("station_no"))
    if code and label.startswith(f"{code}_"):
        label = label[len(code) + 1 :]
    return label or code or "Unknown station"


def _parse_timestamp(value: object) -> datetime | None:
    """ISO-8601 with a trailing Z, as the feed publishes it."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _float(value: object) -> float | None:
    """A coordinate, or None when it is missing or unparseable."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


#: The feed names states in full; the platform keys them by CPCB code.
_STATE_CODES: dict[str, str] = {
    "Uttarakhand": "UK",
    "Uttar Pradesh": "UP",
    "Haryana": "HR",
    "Bihar": "BR",
    "Jharkhand": "JH",
    "West Bengal": "WB",
    "Delhi": "DL",
    "Rajasthan": "RJ",
    "Madhya Pradesh": "MP",
    "Chhattisgarh": "CG",
    "Himachal Pradesh": "HP",
}
