"""What the platform actually holds, measured from the database.

The report is computed, never written by hand: every number comes from a
``COUNT`` or ``MIN``/``MAX`` over the tables, and "available in source" comes
from the provider's resource catalogue. A state the source lists but which
produced no rows is reported as such, with the reason where one is known,
rather than dropped from the table.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.water import (
    District,
    MonitoringStation,
    State,
    WaterBody,
    WaterQualityObservation,
)
from app.models.water_geo import AdminBoundary, City, WaterBodyGeometry


def _source_states(provider_key: str) -> dict[str, dict]:
    """State code -> what the provider's catalogue says it publishes."""
    from app.water.providers import get_provider

    provider = get_provider(provider_key)
    if not hasattr(provider, "catalogue"):
        # Providers without a resource catalogue: what they would fetch is
        # what they publish.
        states: dict[str, dict] = {}
        for plan in provider.plans():
            code = (plan.state_code or "").upper()
            entry = states.setdefault(
                code,
                {
                    "code": code,
                    "name": code,
                    "resources": 0,
                    "active_resources": 0,
                    "fetchable_resources": 0,
                },
            )
            for key in ("resources", "active_resources", "fetchable_resources"):
                entry[key] += 1
        return states
    catalogue = provider.catalogue()
    states = {}
    for resource in catalogue["resources"]:
        code = resource["state_code"]
        entry = states.setdefault(
            code,
            {
                "code": code,
                "name": catalogue["states"].get(code, code),
                "resources": 0,
                "active_resources": 0,
                "fetchable_resources": 0,
            },
        )
        entry["resources"] += 1
        if resource.get("datastore_active"):
            entry["active_resources"] += 1
            if resource["year_from"] < 2026:
                entry["fetchable_resources"] += 1
    return states


def _iso(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def coverage_report(db: Session, provider_key: str = "cpcb_nwdp") -> dict:
    """Totals plus one row per state the source lists."""
    source_states = _source_states(provider_key)

    body_counts = dict(
        db.execute(
            select(WaterBody.state_id, func.count(WaterBody.id)).group_by(
                WaterBody.state_id
            )
        ).all()
    )
    type_counts: dict[int | None, dict[str, int]] = {}
    for state_id, water_type, n in db.execute(
        select(
            WaterBody.state_id, WaterBody.water_type, func.count(WaterBody.id)
        ).group_by(WaterBody.state_id, WaterBody.water_type)
    ).all():
        type_counts.setdefault(state_id, {})[str(water_type)] = n
    station_counts = dict(
        db.execute(
            select(MonitoringStation.state_id, func.count(MonitoringStation.id)).group_by(
                MonitoringStation.state_id
            )
        ).all()
    )
    district_counts = dict(
        db.execute(
            select(District.state_id, func.count(District.id)).group_by(District.state_id)
        ).all()
    )
    obs_rows = db.execute(
        select(
            MonitoringStation.state_id,
            func.count(WaterQualityObservation.id),
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
        )
        .join(
            MonitoringStation, MonitoringStation.id == WaterQualityObservation.station_id
        )
        .group_by(MonitoringStation.state_id)
    ).all()
    obs = {row[0]: row[1:] for row in obs_rows}

    loaded_states = {s.code: s for s in db.scalars(select(State))}
    rows: list[dict] = []
    for code in sorted(set(source_states) | set(loaded_states)):
        src = source_states.get(code)
        state = loaded_states.get(code)
        sid = state.id if state else None
        n_obs, first, last = obs.get(sid, (0, None, None)) if sid else (0, None, None)
        if n_obs:
            note = ""
        elif src is None:
            note = "Loaded but not in the source catalogue."
        elif src["fetchable_resources"] == 0:
            note = "Source lists this state but publishes no queryable resource for it."
        else:
            note = "Source resources returned no usable rows."
        rows.append(
            {
                "code": code,
                "name": state.name if state else (src or {}).get("name", code),
                "in_source": src is not None,
                "source_resources": (src or {}).get("fetchable_resources", 0),
                "loaded": bool(n_obs),
                "districts": district_counts.get(sid, 0) if sid else 0,
                "water_bodies": body_counts.get(sid, 0) if sid else 0,
                "water_bodies_by_type": type_counts.get(sid, {}) if sid else {},
                "stations": station_counts.get(sid, 0) if sid else 0,
                "observations": n_obs,
                "date_min": _iso(first),
                "date_max": _iso(last),
                "note": note,
            }
        )

    by_type = {
        str(t): n
        for t, n in db.execute(
            select(WaterBody.water_type, func.count(WaterBody.id)).group_by(
                WaterBody.water_type
            )
        ).all()
    }
    first_all, last_all = db.execute(
        select(
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
        )
    ).one()
    geometry_counts = dict(
        db.execute(
            select(WaterBody.geometry_status, func.count(WaterBody.id)).group_by(
                WaterBody.geometry_status
            )
        ).all()
    )
    boundary_counts = dict(
        db.execute(
            select(AdminBoundary.level, func.count(AdminBoundary.id)).group_by(
                AdminBoundary.level
            )
        ).all()
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": provider_key,
        "totals": {
            "states_available_in_source": len(source_states),
            "states_loaded": sum(1 for r in rows if r["loaded"]),
            "states_without_data": [r["code"] for r in rows if not r["loaded"]],
            "districts": db.scalar(select(func.count(District.id))) or 0,
            "cities": db.scalar(select(func.count(City.id))) or 0,
            "water_bodies": sum(by_type.values()),
            "water_bodies_by_type": by_type,
            "stations": db.scalar(select(func.count(MonitoringStation.id))) or 0,
            "stations_with_coordinates": db.scalar(
                select(func.count(MonitoringStation.id)).where(
                    MonitoringStation.latitude.is_not(None)
                )
            )
            or 0,
            "observations": db.scalar(select(func.count(WaterQualityObservation.id)))
            or 0,
            "date_min": _iso(first_all),
            "date_max": _iso(last_all),
            "geometries": db.scalar(select(func.count(WaterBodyGeometry.id))) or 0,
            "geometry_status": geometry_counts,
            "boundaries": boundary_counts,
        },
        "states": rows,
    }


def render_markdown(report: dict) -> str:
    """The report as the DATASET_COVERAGE.md document."""
    t = report["totals"]
    types = ", ".join(
        f"{k.replace('_', ' ')} {v:,}"
        for k, v in sorted(t["water_bodies_by_type"].items(), key=lambda kv: -kv[1])
    )
    lines = [
        "# Dataset coverage",
        "",
        f"Generated {report['generated_at']} by `python -m app.water.cli coverage "
        "--markdown` from the local database. Every figure is a count over the "
        "tables; nothing here is estimated.",
        "",
        "## Totals",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| States / UTs listed by the source | {t['states_available_in_source']} |",
        f"| States / UTs with observations loaded | {t['states_loaded']} |",
        f"| States / UTs without data | {len(t['states_without_data'])} "
        f"({', '.join(t['states_without_data']) or 'none'}) |",
        f"| Districts | {t['districts']:,} |",
        f"| Cities (curated district groupings) | {t['cities']:,} |",
        f"| Water bodies | {t['water_bodies']:,} ({types}) |",
        f"| Monitoring stations | {t['stations']:,} "
        f"({t['stations_with_coordinates']:,} with coordinates) |",
        f"| Observations | {t['observations']:,} |",
        f"| Observation dates | {t['date_min']} to {t['date_max']} |",
        f"| Water-body geometries cached | {t['geometries']:,} |",
        "| Administrative boundaries | "
        + (", ".join(f"{k} {v:,}" for k, v in t["boundaries"].items()) or "none")
        + " |",
        "",
        "The latest date differs by state: most state extracts end in 2020 or "
        "2021, and only a few stations have anything newer (see the Latest "
        "column). The national upper date must not be read as the date of the "
        "data in general. See LIMITATIONS.md.",
        "",
        "## By state / UT",
        "",
        "| Code | State / UT | Source resources | Districts | Water bodies | "
        "Stations | Observations | First | Latest | Note |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for r in report["states"]:
        lines.append(
            f"| {r['code']} | {r['name']} | {r['source_resources']} | "
            f"{r['districts']:,} | {r['water_bodies']:,} | {r['stations']:,} | "
            f"{r['observations']:,} | {r['date_min'] or '—'} | "
            f"{r['date_max'] or '—'} | {r['note']} |"
        )
    lines.append("")
    return "\n".join(lines)
