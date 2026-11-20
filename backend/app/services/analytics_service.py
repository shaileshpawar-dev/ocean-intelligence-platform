"""Temporal analytics over stored detections.

Every series here is derived from persisted events and observations. Nothing
is back-filled or smoothed into existence. Where a region has no data for a
day, that day is absent from the series and ``coverage_days`` reports how much
of the requested window was actually observed -- so a flat line caused by a
satellite revisit gap cannot be mistaken for a genuinely quiet week.

This replaces ``seed_history()``, which fabricated thirty days of history by
perturbing a single snapshot with random noise and then reported trends over
that noise.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.forecasting.baseline import trend_slope
from app.models import (
    EvidenceLevel,
    PollutionEvent,
    PollutionSignature,
    Region,
    SatelliteObservation,
    ZoneHistory,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class RegionTrend:
    """A region's daily activity series over a window."""

    region_code: str
    region_name: str
    parent_region: str | None
    series: list[dict]
    latest_risk: float | None
    change: float | None
    slope_per_day: float | None
    coverage_days: int
    window_days: int
    contains_simulated_data: bool

    def to_dict(self) -> dict:
        """Serialise the trend, deriving coverage_ratio for the client."""
        return {
            "region_code": self.region_code,
            "region_name": self.region_name,
            "parent_region": self.parent_region,
            "series": self.series,
            "latest_risk": self.latest_risk,
            "change": self.change,
            "slope_per_day": self.slope_per_day,
            "coverage_days": self.coverage_days,
            "window_days": self.window_days,
            "coverage_ratio": round(self.coverage_days / self.window_days, 3)
            if self.window_days
            else 0.0,
            "contains_simulated_data": self.contains_simulated_data,
        }


def rebuild_history(db: Session) -> int:
    """Recompute daily :class:`ZoneHistory` buckets from stored events.

    Idempotent: deletes and rewrites the aggregate table. Cheap at the scale
    of a few hundred cells; swap for an incremental upsert if the event table
    grows past millions of rows.

    Returns:
        Number of daily buckets written.
    """
    db.execute(delete(ZoneHistory))

    rows = db.execute(
        select(
            PollutionEvent.region_id,
            func.date(PollutionEvent.detected_at).label("bucket"),
            func.count(PollutionEvent.id),
            func.avg(PollutionEvent.confidence),
            func.avg(PollutionEvent.risk_score),
            func.max(PollutionEvent.risk_score),
            func.sum(PollutionEvent.estimated_area_km2),
            func.max(PollutionEvent.evidence_level),
        ).group_by(PollutionEvent.region_id, "bucket")
    ).all()

    # Mean backscatter per region-day comes from the observation table, since
    # a cell can be observed without producing an event.
    backscatter = {
        (region_id, bucket): mean_db
        for region_id, bucket, mean_db in db.execute(
            select(
                SatelliteObservation.region_id,
                func.date(SatelliteObservation.acquired_at).label("bucket"),
                func.avg(SatelliteObservation.mean_db),
            ).group_by(SatelliteObservation.region_id, "bucket")
        ).all()
    }

    written = 0
    for region_id, bucket, count, mean_conf, mean_risk, max_risk, area, evidence in rows:
        bucket_dt = _to_datetime(bucket)
        if bucket_dt is None:
            continue
        db.add(
            ZoneHistory(
                region_id=region_id,
                bucket_date=bucket_dt,
                event_count=count,
                mean_confidence=mean_conf,
                mean_risk_score=mean_risk,
                max_risk_score=max_risk,
                total_area_km2=area,
                mean_backscatter_db=backscatter.get((region_id, bucket)),
                evidence_level=evidence or str(EvidenceLevel.DETECTED),
            )
        )
        written += 1

    db.commit()
    logger.info("history_rebuilt", extra={"buckets": written})
    return written


def _to_datetime(value: object) -> datetime | None:
    """Normalise the DB's date-group output to an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def get_trends(
    db: Session, days: int = 30, parent_region: str | None = None
) -> list[RegionTrend]:
    """Daily risk/activity series per region over the last ``days`` days.

    Args:
        db: Active session.
        days: Window length.
        parent_region: Optional filter, e.g. ``"Arabian Sea"``.

    Returns:
        Trends sorted by latest risk, highest first.
    """
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = (
        select(ZoneHistory, Region)
        .join(Region, Region.id == ZoneHistory.region_id)
        .where(ZoneHistory.bucket_date >= since)
        # Stage-2 refined sub-cells are excluded. They are subdivisions of a
        # monitored region, so counting both double-counts the same water --
        # and because a sub-cell only exists from the moment it was refined, it
        # carries a day or two of history at most. Including them put regions
        # in the Forecasts dropdown that could never be forecast, which is the
        # failure this filter exists to prevent: running stage-2 refine would
        # otherwise reintroduce "insufficient history" on a page that works.
        .where(Region.code.not_like("%\\_\\_r%c%", escape="\\"))
        .order_by(ZoneHistory.bucket_date)
    )
    if parent_region:
        stmt = stmt.where(Region.parent_code == parent_region)

    grouped: dict[int, list[tuple[ZoneHistory, Region]]] = defaultdict(list)
    for history, region in db.execute(stmt).all():
        grouped[region.id].append((history, region))

    trends: list[RegionTrend] = []
    for rows in grouped.values():
        region = rows[0][1]
        series = [
            {
                "date": h.bucket_date.date().isoformat(),
                "event_count": h.event_count,
                "mean_risk": round(h.mean_risk_score, 2) if h.mean_risk_score else None,
                "max_risk": round(h.max_risk_score, 2) if h.max_risk_score else None,
                "mean_confidence": round(h.mean_confidence, 3)
                if h.mean_confidence
                else None,
                "total_area_km2": round(h.total_area_km2, 2)
                if h.total_area_km2
                else None,
                "mean_backscatter_db": round(h.mean_backscatter_db, 2)
                if h.mean_backscatter_db
                else None,
                "evidence_level": h.evidence_level,
            }
            for h, _ in rows
        ]
        risk_values = [
            h.mean_risk_score for h, _ in rows if h.mean_risk_score is not None
        ]

        trends.append(
            RegionTrend(
                region_code=region.code,
                region_name=region.name,
                parent_region=region.parent_code,
                series=series,
                latest_risk=round(risk_values[-1], 2) if risk_values else None,
                change=(
                    round(risk_values[-1] - risk_values[0], 2)
                    if len(risk_values) > 1
                    else None
                ),
                slope_per_day=(
                    round(s, 4) if (s := trend_slope(risk_values)) is not None else None
                ),
                coverage_days=len(series),
                window_days=days,
                contains_simulated_data=any(
                    h.evidence_level == str(EvidenceLevel.SIMULATED) for h, _ in rows
                ),
            )
        )

    trends.sort(key=lambda t: (t.latest_risk is None, -(t.latest_risk or 0)))
    return trends


def region_trend_slopes(db: Session, days: int = 14) -> dict[int, float]:
    """Risk-points-per-day slope per region id, for the risk engine.

    Regions with fewer than three observed days are omitted, so the risk
    engine records ``historical_trend`` as a missing factor rather than
    treating an unknown trend as flat.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(ZoneHistory.region_id, ZoneHistory.mean_risk_score)
        .where(
            ZoneHistory.bucket_date >= since,
            ZoneHistory.mean_risk_score.is_not(None),
        )
        .order_by(ZoneHistory.region_id, ZoneHistory.bucket_date)
    ).all()

    series: dict[int, list[float]] = defaultdict(list)
    for region_id, risk in rows:
        series[region_id].append(risk)

    slopes: dict[int, float] = {}
    for region_id, values in series.items():
        slope = trend_slope(values)
        if slope is not None:
            slopes[region_id] = slope
    return slopes


def get_region_series(
    db: Session, region_code: str, days: int = 60
) -> tuple[list[float], list[date]]:
    """Daily mean-risk series for one region, for the forecaster.

    Gaps are forward-filled to produce the regular daily grid the smoothing
    models require. Forward-filling is stated explicitly in the forecast
    response so a consumer knows the series was made regular.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(ZoneHistory.bucket_date, ZoneHistory.mean_risk_score)
        .join(Region, Region.id == ZoneHistory.region_id)
        .where(Region.code == region_code, ZoneHistory.bucket_date >= since)
        .order_by(ZoneHistory.bucket_date)
    ).all()

    observed = {d.date(): risk for d, risk in rows if risk is not None}
    if not observed:
        return [], []

    start, end = min(observed), max(observed)
    values: list[float] = []
    dates: list[date] = []
    last = observed[start]
    current = start
    while current <= end:
        last = observed.get(current, last)
        values.append(last)
        dates.append(current)
        current += timedelta(days=1)
    return values, dates


def summary_counts(db: Session) -> dict:
    """Headline counts for the dashboard overview strip."""
    total_events = db.scalar(select(func.count(PollutionEvent.id))) or 0
    critical = (
        db.scalar(
            select(func.count(PollutionEvent.id)).where(
                PollutionEvent.severity == "CRITICAL"
            )
        )
        or 0
    )
    high = (
        db.scalar(
            select(func.count(PollutionEvent.id)).where(PollutionEvent.severity == "HIGH")
        )
        or 0
    )
    # Area is reported in two separate figures on purpose. Summing them into
    # one "total affected area" tile would put a number in the millions of
    # km^2 on the dashboard, because coarse dark formations span whole
    # monitoring cells. That figure is real, but it measures low-backscatter
    # water, not pollution, and presenting it as the latter would be exactly
    # the kind of impressive-but-meaningless statistic this platform avoids.
    slick_scale_area = (
        db.scalar(
            select(func.sum(PollutionEvent.estimated_area_km2)).where(
                PollutionEvent.signature == str(PollutionSignature.OIL_LIKE_SIGNATURE)
            )
        )
        or 0.0
    )
    dark_water_extent = (
        db.scalar(select(func.sum(PollutionEvent.estimated_area_km2))) or 0.0
    )
    observations = db.scalar(select(func.count(SatelliteObservation.id))) or 0
    simulated = (
        db.scalar(
            select(func.count(PollutionEvent.id)).where(
                PollutionEvent.evidence_level == str(EvidenceLevel.SIMULATED)
            )
        )
        or 0
    )
    return {
        "total_events": total_events,
        "critical_events": critical,
        "high_events": high,
        # Extent of regions whose signature is slick-plausible. This is the
        # figure a dashboard should headline.
        "slick_scale_area_km2": round(float(slick_scale_area), 2),
        # Extent of all low-backscatter regions, dominated by coarse-grid
        # dark formations. Useful for monitoring coverage; NOT a pollution
        # figure, and must not be labelled as one.
        "dark_water_extent_km2": round(float(dark_water_extent), 2),
        "observations": observations,
        "simulated_events": simulated,
        "contains_simulated_data": simulated > 0,
    }
