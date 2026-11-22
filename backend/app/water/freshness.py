"""Source-cadence-aware data freshness.

A single global staleness rule is wrong for this domain. CPCB's manual
surface-water programme samples a station roughly monthly; a telemetry gauge
reports hourly. Calling both "stale after 7 days" would flag every manual
observation in the country as a problem while letting a silent telemetry
station look healthy for six days.

So freshness is judged **relative to what the source promises**. The provider
declares its expected cadence, and an observation is late only when it is late
*for that cadence*.

This module is also where the platform's sharpest honesty rule is enforced:
an observation is never described as "current". It is the *latest available*
observation, and its age is always stated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class Cadence(StrEnum):
    """How often a source is expected to publish a new observation."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    IRREGULAR = "irregular"
    UNKNOWN = "unknown"


# Nominal period of each cadence, in days. ``None`` means the cadence gives no
# basis for an expectation, so no lateness judgement is made at all.
CADENCE_DAYS: dict[Cadence, float | None] = {
    Cadence.HOURLY: 1 / 24,
    Cadence.DAILY: 1.0,
    Cadence.WEEKLY: 7.0,
    Cadence.MONTHLY: 31.0,
    Cadence.QUARTERLY: 92.0,
    Cadence.ANNUAL: 366.0,
    Cadence.IRREGULAR: None,
    Cadence.UNKNOWN: None,
}

CADENCE_LABELS: dict[Cadence, str] = {
    Cadence.HOURLY: "Hourly",
    Cadence.DAILY: "Daily",
    Cadence.WEEKLY: "Weekly",
    Cadence.MONTHLY: "Monthly",
    Cadence.QUARTERLY: "Quarterly",
    Cadence.ANNUAL: "Annual",
    Cadence.IRREGULAR: "Irregular",
    Cadence.UNKNOWN: "Unknown",
}

# Multiples of the nominal period at which an observation becomes late, then
# so late that the platform refuses to characterise the water body's present
# state from it at all.
LATE_MULTIPLE = 2.0
NO_RECENT_MULTIPLE = 12.0

# A floor under the refusal horizon. Twelve nominal periods is a sensible
# multiple for a monthly programme and far too tight for an hourly one: it
# would declare an hourly analyser's reading unfit to describe the present
# after twelve hours, so the Ganga's page would flip between "described" and
# "no recent data" according to when the ingestion job last ran rather than
# according to anything about the river. River quality does not become
# meaningless overnight, so no source's refusal horizon is shorter than this.
# It is the same two days the national coverage split calls "current data",
# deliberately: one threshold governs both, so the count of water bodies that
# can be described now cannot disagree with the pages that describe them.
MIN_NO_RECENT_DAYS = 2.0

# A ceiling on it, for the opposite reason. Twelve missed months is not a
# monthly programme running late, it is a programme that stopped, and an
# Indian water body sampled more than a season ago was sampled in a different
# season: pre-monsoon, monsoon and post-monsoon quality at the same station
# differ enough that the older reading says nothing about now. Without this
# ceiling the engine would give a present-tense status to a sample eleven
# months old while the overview told the reader that only 26 water bodies can
# be described at all.
MAX_NO_RECENT_DAYS = 90.0


def refusal_horizon_days(cadence: Cadence) -> float | None:
    """How old an observation may be before it stops describing the present.

    ``None`` for cadences that make no promise; those fall back to
    :data:`ABSOLUTE_NO_RECENT_DAYS`.

    Three considerations meet here, which is why this is a function and not a
    constant:

    * twelve nominal periods, the source's own promise missed twelve times over;
    * never sooner than :data:`MIN_NO_RECENT_DAYS`, so an hourly analyser is
      not declared unusable between two runs of the ingestion job;
    * never later than :data:`MAX_NO_RECENT_DAYS`, so a stopped monthly
      programme is not read as a description of today --- except that a source
      which genuinely reports less often than that is not overdue merely for
      keeping to its schedule, so the horizon is never shorter than twice its
      own cadence. A quarterly programme that published 100 days ago is on
      time, and the engine must not call it stale.
    """
    period = CADENCE_DAYS[cadence]
    if period is None:
        return None
    return max(
        MIN_NO_RECENT_DAYS,
        period * LATE_MULTIPLE,
        min(period * NO_RECENT_MULTIPLE, MAX_NO_RECENT_DAYS),
    )

# For irregular and unknown cadences there is no promise to measure against,
# so a single absolute horizon applies instead. Three years is deliberately
# generous: it is long enough not to condemn a slow official programme, and
# short enough that nobody mistakes the reading for a description of today.
ABSOLUTE_NO_RECENT_DAYS = 1095.0


class Freshness(StrEnum):
    """How current an observation is, relative to its source's cadence."""

    RECENT = "recent"
    """Newer than one nominal period. As current as the source ever gets."""

    WITHIN_CADENCE = "within_cadence"
    """Older than one period but within the expected reporting window."""

    OLDER_THAN_CADENCE = "older_than_cadence"
    """The source is overdue. The reading still describes something real."""

    NO_RECENT_DATA = "no_recent_data"
    """So old that it must not be read as the water body's present state."""

    NEVER_OBSERVED = "never_observed"
    """No observation exists at all. Not the same as clean."""


FRESHNESS_LABELS: dict[Freshness, str] = {
    Freshness.RECENT: "Recent",
    Freshness.WITHIN_CADENCE: "Within expected cadence",
    Freshness.OLDER_THAN_CADENCE: "Older than expected cadence",
    Freshness.NO_RECENT_DATA: "No recent data",
    Freshness.NEVER_OBSERVED: "Never observed",
}


def _age_phrase(age_days: float | None) -> str:
    """The age in the unit a reader would use for it.

    An hourly source measured eleven hours ago was being reported as "0 days
    ago", which reads as a contradiction beside a sentence calling it old.
    """
    days = age_days or 0.0
    if days < 1.0:
        hours = int(days * 24)
        if hours < 1:
            minutes = max(int(days * 1440), 1)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    whole = int(days)
    return f"{whole} day{'s' if whole != 1 else ''} ago"


@dataclass(slots=True)
class FreshnessAssessment:
    """The age of the latest observation, judged against source cadence."""

    freshness: Freshness
    observed_at: datetime | None
    age_days: float | None
    cadence: Cadence
    evaluated_at: datetime

    @property
    def describes_present_state(self) -> bool:
        """Whether this observation may inform a present-tense claim.

        The status engine consults this before it will say anything about a
        water body's condition. When it is false the engine reports
        ``NO_RECENT_DATA`` and shows the historical reading with its date,
        instead of implying it is true today.
        """
        return self.freshness in (
            Freshness.RECENT,
            Freshness.WITHIN_CADENCE,
            Freshness.OLDER_THAN_CADENCE,
        )

    def summary(self) -> str:
        """A sentence stating the age and refusing the word 'current'."""
        if self.observed_at is None:
            return "No observation has ever been recorded for this location."

        date = self.observed_at.strftime("%d %b %Y")
        age = _age_phrase(self.age_days)
        cadence = CADENCE_LABELS[self.cadence].lower()

        if self.freshness is Freshness.NO_RECENT_DATA:
            return (
                f"Latest available observation is from {date}, {age}. "
                "That is too old to describe the water body's present state."
            )
        if self.freshness is Freshness.OLDER_THAN_CADENCE:
            return (
                f"Latest available observation is from {date}, {age}. "
                f"The source reports {cadence}, so this is overdue."
            )
        return (
            f"Latest available observation is from {date}, {age}, "
            f"within the source's {cadence} reporting cadence."
        )

    def to_dict(self) -> dict:
        """Serialise for the API."""
        return {
            "freshness": str(self.freshness),
            "label": FRESHNESS_LABELS[self.freshness],
            "observed_at": (self.observed_at.isoformat() if self.observed_at else None),
            "age_days": round(self.age_days, 1) if self.age_days is not None else None,
            "expected_cadence": str(self.cadence),
            "expected_cadence_label": CADENCE_LABELS[self.cadence],
            "describes_present_state": self.describes_present_state,
            "summary": self.summary(),
        }


def assess(
    observed_at: datetime | None,
    cadence: Cadence = Cadence.UNKNOWN,
    *,
    now: datetime | None = None,
) -> FreshnessAssessment:
    """Judge an observation's age against its source's expected cadence."""
    now = now or datetime.now(UTC)
    if observed_at is not None and observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)

    if observed_at is None:
        return FreshnessAssessment(
            freshness=Freshness.NEVER_OBSERVED,
            observed_at=None,
            age_days=None,
            cadence=cadence,
            evaluated_at=now,
        )

    age_days = (now - observed_at).total_seconds() / 86400.0
    # A future-dated observation is a data-quality problem, not freshness.
    # Clamping keeps the age non-negative; the quality flag is raised during
    # ingestion, where the record can actually be inspected.
    age_days = max(age_days, 0.0)

    period = CADENCE_DAYS[cadence]

    if period is None:
        level = (
            Freshness.NO_RECENT_DATA
            if age_days > ABSOLUTE_NO_RECENT_DAYS
            else Freshness.WITHIN_CADENCE
        )
    elif age_days > refusal_horizon_days(cadence):
        level = Freshness.NO_RECENT_DATA
    elif age_days > period * LATE_MULTIPLE:
        level = Freshness.OLDER_THAN_CADENCE
    elif age_days > period:
        level = Freshness.WITHIN_CADENCE
    else:
        level = Freshness.RECENT

    return FreshnessAssessment(
        freshness=level,
        observed_at=observed_at,
        age_days=age_days,
        cadence=cadence,
        evaluated_at=now,
    )
