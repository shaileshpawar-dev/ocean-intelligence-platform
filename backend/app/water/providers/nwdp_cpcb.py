"""CPCB surface-water quality via the National Water Data Portal.

What this actually reads
------------------------
The National Water Informatics Centre publishes CPCB's manual surface-water
monitoring programme on a CKAN portal at ``nwdp.nwic.gov.in``. Three datasets
-- physical, chemical and biological parameters -- are split into 315 CSV
resources, one per state per period, and every one of them is backed by
CKAN's datastore. That means the rows can be queried over HTTP with paging
instead of downloading and parsing 315 CSV files.

Verified against the live portal before this adapter was written:

* ``/api/3/action/datastore_search`` works, unauthenticated, for every
  resource. No API key, no registration.
* ``/api/3/action/datastore_search_sql`` is **disabled** -- it returns
  "Action name not known". So aggregation happens in this process, after
  paging, rather than being pushed to the server.
* Periods are ``1961-2020``, ``2021-2025`` and ``2026-2030``. The last is
  present but **empty** for every state sampled: the resources exist as
  forward-dated placeholders.
* The ``River``, ``Basin`` and ``Tributary`` columns are empty in every row
  sampled nationwide. Water-body identity therefore comes from parsing the
  station name -- see :mod:`app.water.matching`.
* Values arrive as text, with ``'-'``, ``''`` and ``None`` all meaning "not
  measured", and occasional censored values such as ``'<0.01'``.

Why the cadence is MONTHLY but the data is old
----------------------------------------------
CPCB's programme samples a station roughly monthly, so ``Cadence.MONTHLY`` is
the honest declaration of intent. The data currently published under the
"2021-2025" resources is, however, entirely from 2021. That gap is precisely
what the freshness engine exists to surface: the platform reports a monthly
cadence and an observation several years old, and concludes ``NO_RECENT_DATA``
rather than describing a 2021 sample as the river's present condition.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.water.freshness import Cadence
from app.water.parameters import parse_value
from app.water.parameters import resolve as resolve_parameter
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    ProviderUnavailableError,
    WaterDataProvider,
)

logger = get_logger(__name__)

API_BASE = "https://nwdp.nwic.gov.in/api/3/action"
CATALOGUE_PATH = Path(__file__).parent / "data" / "nwdp_cpcb_catalogue.json"

PAGE_SIZE = 1000
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3
BACKOFF_SECONDS = 2.0

# Columns that describe the station and the sample, not a measurement. Every
# other column is looked up in the parameter registry.
METADATA_COLUMNS = frozenset(
    {
        "_id",
        "slno",
        "station",
        "agency",
        "state lgd code",
        "state",
        "district lgd code",
        "district",
        "tehsil",
        "block",
        "village",
        "river",
        "basin",
        "tributary",
        "subtributary",
        "subsubtributary",
        "local river",
        "latitude",
        "longitude",
        "data acquisition time",
    }
)

# India's bounding box, used only to flag implausible coordinates. Generous on
# purpose: it includes the island territories, so a Lakshadweep station is not
# mistaken for bad data.
INDIA_BBOX = (6.0, 68.0, 37.5, 97.5)


def _get(key: str, row: dict) -> str | None:
    """Case-insensitive column read."""
    for k, v in row.items():
        if k.strip().lower() == key:
            return None if v is None else str(v)
    return None


def _clean(text: str | None) -> str | None:
    """Normalise a metadata cell, mapping the source's null tokens to None."""
    if text is None:
        return None
    value = str(text).strip()
    return None if value in {"", "-", "--", "NA", "N/A", "null", "None"} else value


def _parse_timestamp(text: str | None) -> datetime | None:
    """Parse the portal's ``DD-MM-YYYY HH:MM`` acquisition time.

    Day-first is not a guess: values such as ``12-01-2021`` alongside
    ``05-10-2021`` in the same column only resolve consistently as day-first,
    and the portal's own CSV headers describe it that way.
    """
    raw = _clean(text)
    if not raw:
        return None
    for fmt in ("%d-%m-%Y %H:%M", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_coord(text: str | None) -> float | None:
    """Parse a coordinate, returning None rather than raising."""
    raw = _clean(text)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class NWDPCPCBProvider(WaterDataProvider):
    """Reads CPCB surface-water observations from the NWDP CKAN datastore."""

    def __init__(self, *, catalogue_path: Path | None = None) -> None:
        """Create the provider, optionally overriding the bundled catalogue."""
        self._catalogue_path = catalogue_path or CATALOGUE_PATH
        self._catalogue: dict | None = None

    # -- Description -------------------------------------------------------
    @property
    def info(self) -> ProviderInfo:
        """Self-description, including the limitations found in testing."""
        return ProviderInfo(
            key="cpcb_nwdp",
            name="CPCB Surface Water Quality (Manual)",
            organisation="Central Pollution Control Board via National Water "
            "Informatics Centre",
            url="https://nwdp.nwic.gov.in/dataset/?organization=cpcb",
            dataset="Surface Water Quality (Manual) — physical, chemical and "
            "biological parameters",
            licence="Other (Open)",
            cadence=Cadence.MONTHLY,
            access="public",
            implemented=True,
            notes=[
                "Public CKAN datastore API; no key or registration required.",
                "SQL endpoint is disabled upstream, so aggregation happens "
                "in-process after paging.",
                "The River, Basin and Tributary columns are empty in the "
                "published extracts; water bodies are resolved by parsing "
                "station names.",
                "Resources for 2026-2030 exist but are empty placeholders.",
            ],
        )

    # -- Catalogue ---------------------------------------------------------
    def catalogue(self) -> dict:
        """Load the bundled resource catalogue.

        Bundled rather than discovered on every run so that ingestion works
        offline and in tests, and so a portal outage cannot stop the platform
        from describing what it would fetch. :meth:`refresh_catalogue`
        re-discovers it from the live API when needed.
        """
        if self._catalogue is None:
            self._catalogue = json.loads(self._catalogue_path.read_text(encoding="utf-8"))
        return self._catalogue

    def refresh_catalogue(self) -> dict:
        """Re-discover resources from the live portal.

        Not called during normal ingestion. It exists so the catalogue can be
        regenerated deliberately when the portal adds a period or a state,
        with the result reviewed rather than silently adopted.
        """
        catalogue = self.catalogue()
        discovered: list[dict] = []
        for family, package in catalogue["packages"].items():
            payload = self._call("package_show", {"id": package})
            for resource in payload["result"].get("resources", []):
                if (resource.get("format") or "").upper() != "CSV":
                    continue
                name = (resource.get("url") or "").split("/")[-1].lower()
                parts = name.replace(".csv", "").split("_")
                if len(parts) < 3:
                    continue
                code, year_from, year_to = parts[-3:], None, None
                try:
                    state_code = code[0].upper()
                    year_from = int(code[1])
                    year_to = int(code[2])
                except (ValueError, IndexError):
                    continue
                discovered.append(
                    {
                        "family": family,
                        "state_code": state_code,
                        "year_from": year_from,
                        "year_to": year_to,
                        "resource_id": resource["id"],
                        "datastore_active": bool(resource.get("datastore_active")),
                    }
                )
        return {**catalogue, "resources": discovered}

    # -- Plans -------------------------------------------------------------
    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        """One plan per (state, family, period) resource.

        Empty forward-dated placeholders are excluded: fetching them costs a
        request and can only ever return nothing.
        """
        catalogue = self.catalogue()
        wanted = {s.upper() for s in states} if states else None
        plans: list[FetchPlan] = []

        for resource in catalogue["resources"]:
            if not resource.get("datastore_active"):
                continue
            if resource["year_from"] >= 2026:
                continue
            if wanted and resource["state_code"] not in wanted:
                continue
            state_name = catalogue["states"].get(
                resource["state_code"], resource["state_code"]
            )
            plans.append(
                FetchPlan(
                    identifier=resource["resource_id"],
                    description=(
                        f"{state_name} — {resource['family']} "
                        f"({resource['year_from']}-{resource['year_to']})"
                    ),
                    state_code=resource["state_code"],
                )
            )
        return plans

    # -- Fetch -------------------------------------------------------------
    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        """Page through one resource, yielding one row per measured value.

        A source row carries a station, a timestamp and up to thirty-odd
        parameter columns. It is exploded into one :class:`ObservationRow`
        per parameter that actually has a value, because the long format is
        what the observation table stores.
        """
        catalogue = self.catalogue()
        state_name = catalogue["states"].get(plan.state_code or "", plan.state_code)
        offset = 0

        while True:
            payload = self._call(
                "datastore_search",
                {
                    "resource_id": plan.identifier,
                    "limit": PAGE_SIZE,
                    "offset": offset,
                },
            )
            result = payload.get("result") or {}
            records = result.get("records") or []
            if not records:
                return

            for record in records:
                yield from self._explode(record, plan, state_name)

            offset += len(records)
            if offset >= int(result.get("total") or 0):
                return

    def _explode(
        self, record: dict, plan: FetchPlan, state_name: str | None
    ) -> Iterator[ObservationRow]:
        """Turn one wide source row into one row per measured parameter."""
        station = _clean(_get("station", record))
        if not station:
            return

        observed_at = _parse_timestamp(_get("data acquisition time", record))
        if observed_at is None:
            # Without a timestamp the value cannot be placed in a series or
            # judged for freshness, which is most of what this platform does.
            return

        latitude = _parse_coord(_get("latitude", record))
        longitude = _parse_coord(_get("longitude", record))

        geo_flags: list[str] = []
        if latitude is not None and longitude is not None:
            lat_min, lon_min, lat_max, lon_max = INDIA_BBOX
            if not (lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max):
                geo_flags.append("coordinates_outside_india")
        elif latitude is None or longitude is None:
            geo_flags.append("coordinates_missing")

        if observed_at > datetime.now(UTC):
            geo_flags.append("future_dated")

        common = {
            "station_name": station,
            "latitude": latitude,
            "longitude": longitude,
            # The resource's own state (from its catalogue code) wins over the
            # free-text column: the Dadra & Nagar Haveli resource labels its
            # rows "Daman & Diu" (the UTs merged in 2020), which collided with
            # the Daman & Diu resource.
            "state_name": state_name or _clean(_get("state", record)),
            "state_code": plan.state_code,
            "district": _clean(_get("district", record)),
            "tehsil": _clean(_get("tehsil", record)),
            "village": _clean(_get("village", record)),
            "agency": _clean(_get("agency", record)),
            "river": _clean(_get("river", record)),
            "basin": _clean(_get("basin", record)),
            "tributary": _clean(_get("tributary", record)),
            "source_reference": (f"nwdp:datastore:{plan.identifier}#{record.get('_id')}"),
        }

        for column, raw in record.items():
            if column.strip().lower() in METADATA_COLUMNS:
                continue
            parameter = resolve_parameter(column)
            if parameter is None:
                continue

            parsed = parse_value(parameter, raw)
            if parsed.is_missing:
                # Not measured. Storing a zero here is the single most
                # dangerous thing this pipeline could do, because zero BOD
                # reads as pristine water.
                continue

            yield ObservationRow(
                parameter_key=parameter.key,
                observed_at=observed_at,
                value=parsed.value,
                unit=parameter.unit,
                normalized_value=parsed.normalized_value,
                normalized_unit=parsed.unit,
                qualitative_value=parsed.qualitative,
                raw_value=parsed.raw,
                quality_flags=[*parsed.flags, *geo_flags],
                **common,
            )

    # -- HTTP --------------------------------------------------------------
    def _call(self, action: str, params: dict) -> dict:
        """Call one CKAN action with retry and backoff.

        Raises :class:`ProviderUnavailableError` once retries are exhausted. It
        never returns a partial or fabricated payload -- the caller must be
        able to tell a failure from an empty result.
        """
        url = f"{API_BASE}/{action}?{urllib.parse.urlencode(params)}"
        last_error = ""

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                request = urllib.request.Request(
                    url, headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not payload.get("success"):
                    raise ProviderUnavailableError(
                        f"CKAN reported failure for {action}: {payload.get('error')}"
                    )
                return payload
            except ProviderUnavailableError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc)
            except json.JSONDecodeError as exc:
                last_error = f"malformed JSON: {exc}"

            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)
                logger.warning(
                    "nwdp_retry",
                    extra={"action": action, "attempt": attempt, "error": last_error},
                )

        raise ProviderUnavailableError(
            f"NWDP {action} failed after {MAX_RETRIES} attempts: {last_error}"
        )

    def health(self) -> tuple[bool, str]:
        """Probe the portal with the cheapest call that proves it works."""
        try:
            self._call("datastore_search", {"resource_id": self._probe_id(), "limit": 1})
        except ProviderUnavailableError as exc:
            return False, str(exc)
        return True, "NWDP CKAN datastore reachable."

    def _probe_id(self) -> str:
        """A resource id known to be datastore-backed, for health checks."""
        for resource in self.catalogue()["resources"]:
            if resource.get("datastore_active") and resource["year_from"] < 2026:
                return str(resource["resource_id"])
        raise ProviderUnavailableError("Catalogue contains no datastore-backed resource.")
