"""Provider abstraction for water-data sources.

Every source the platform can read implements :class:`WaterDataProvider`.
The contract is narrow on purpose -- describe yourself, list what you can
fetch, and yield normalised rows -- because the sources differ enormously in
shape: one offers a CKAN datastore API, another a CSV download, another a
PDF bulletin.

Two rules apply to every implementation.

**A provider never fabricates.** If the upstream call fails, it raises
:class:`ProviderUnavailableError`. It does not return an empty list that the
caller cannot distinguish from "there genuinely is no data", and it does not
substitute cached or synthetic rows silently. The ingestion layer decides
what to do with a failure, and the UI says the source was unavailable.

**A provider declares its cadence.** Freshness is judged against what the
source promises, so a provider that cannot state a cadence returns
``Cadence.UNKNOWN`` rather than a flattering guess.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from app.water.freshness import Cadence


class ProviderError(Exception):
    """Base class for provider failures."""


class ProviderUnavailableError(ProviderError):
    """The upstream source could not be reached or returned an error.

    Distinct from "the source returned no rows", which is a legitimate empty
    result and is never represented by an exception.
    """


@dataclass(slots=True)
class ProviderInfo:
    """Self-description of a source, surfaced in the UI and the API."""

    key: str
    name: str
    organisation: str
    url: str | None = None
    dataset: str | None = None
    licence: str | None = None
    cadence: Cadence = Cadence.UNKNOWN
    access: str = "public"
    """``public``, ``requires_key`` or ``unavailable``."""

    implemented: bool = True
    """False for a declared-but-unbuilt adapter. Shown honestly rather than
    presented as a working integration."""

    source_type: str = "government"
    """``government``, ``state_board``, ``research``, ``satellite``, ``other``.
    A fact about the publisher, not a ranking."""

    observation_method: str | None = None
    """``manual_grab_sample``, ``continuous_sensor``, ``satellite_derived``…"""

    reliability_note: str | None = None
    """What is known about reliability, in words with its basis. Never a
    score: the platform has no basis for scoring an agency."""

    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise for the data-source health view."""
        return {
            "key": self.key,
            "name": self.name,
            "organisation": self.organisation,
            "url": self.url,
            "dataset": self.dataset,
            "licence": self.licence,
            "expected_cadence": str(self.cadence),
            "access": self.access,
            "implemented": self.implemented,
            "source_type": self.source_type,
            "observation_method": self.observation_method,
            "reliability_note": self.reliability_note,
            "notes": self.notes,
        }


@dataclass(slots=True)
class ObservationRow:
    """One normalised measurement, ready for the ingestion pipeline.

    Deliberately flat and provider-agnostic: by the time a row reaches this
    shape, every source-specific quirk -- column naming, unit spelling,
    missing-value tokens -- has already been resolved by the provider.
    """

    station_name: str
    parameter_key: str
    observed_at: datetime
    value: float | None = None
    unit: str | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None
    qualitative_value: str | None = None
    raw_value: str | None = None

    latitude: float | None = None
    longitude: float | None = None
    state_name: str | None = None
    state_code: str | None = None
    district: str | None = None
    tehsil: str | None = None
    village: str | None = None
    agency: str | None = None

    river: str | None = None
    basin: str | None = None
    tributary: str | None = None

    source_reference: str | None = None
    quality_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FetchPlan:
    """One unit of work a provider can execute.

    Exposed so the ingestion layer can page a large source incrementally,
    report progress, and resume, instead of disappearing into one opaque
    multi-hour call.
    """

    identifier: str
    description: str
    state_code: str | None = None
    estimated_records: int | None = None


class WaterDataProvider(ABC):
    """A source of water-quality observations."""

    @property
    @abstractmethod
    def info(self) -> ProviderInfo:
        """Static self-description."""

    @abstractmethod
    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        """Enumerate the fetchable units, optionally restricted to states."""

    @abstractmethod
    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        """Yield normalised rows for one plan.

        Raises:
            ProviderUnavailableError: the source could not be read. Never returns
                an empty iterator to signal failure.
        """

    def resource_total(self, plan: FetchPlan) -> int | None:
        """Rows the source currently reports for one plan, or ``None``.

        Used for incremental sync: when the count is unchanged since the last
        successful ingest, the resource is skipped instead of being paged in
        full. Providers that cannot answer cheaply return ``None``, and the
        resource is always fetched.
        """
        return None

    def health(self) -> tuple[bool, str]:
        """Cheap reachability probe.

        Returns ``(ok, detail)``. The default reports that no probe is
        implemented rather than claiming success.
        """
        return True, "No health probe implemented for this provider."
