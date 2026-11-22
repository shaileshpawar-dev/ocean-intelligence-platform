"""Official source classifications, such as CPCB polluted river stretches.

Why this is an import path with no data behind it
-------------------------------------------------
CPCB publishes its polluted-river-stretch (PRS) assessments as PDF reports.
When this was built (2026-09-21) the report URLs returned an HTML stub or a
404, and no machine-readable table was published on the National Water Data
Portal. Transcribing a PDF by hand would put unverifiable numbers into the
platform's highest-severity label. So the platform ships the model, this
validated importer, and no rows. ``POLLUTED_STRETCH`` therefore never
appears until someone imports a file they have checked against the report.

File format (CSV, UTF-8, header row)
------------------------------------
Required: ``state``, ``river``, ``priority`` (I-V).
Optional: ``stretch``, ``bod_max_mg_l``, ``monitoring_locations``.

Matching to water bodies
------------------------
Deterministic and conservative: the river name is normalised (with the same
spelling canonicalisation as station identity) and must equal a river's
canonical name *in the same state*. Anything else is stored unmatched, visible
in the import report, and has no effect on any status.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enums import WaterBodyType
from app.models.water import State, WaterBody
from app.models.water_geo import SourceClassification
from app.water.matching import canonical_core, normalise_name

PRS_TYPE = "polluted_river_stretch"
PRIORITIES = ("I", "II", "III", "IV", "V")
REQUIRED = ("state", "river", "priority")
_RIVER_WORDS = {"RIVER", "NADI", "R"}


@dataclass(slots=True)
class ImportReport:
    """What an import did, row by row where it matters."""

    rows: int = 0
    stored: int = 0
    matched: int = 0
    rejected: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise for the CLI."""
        return {
            "rows": self.rows,
            "stored": self.stored,
            "matched_to_water_bodies": self.matched,
            "unmatched": self.unmatched,
            "rejected": self.rejected,
        }


def _river_key(name: str) -> str:
    tokens = [t for t in normalise_name(name).split() if t not in _RIVER_WORDS]
    return canonical_core(" ".join(tokens))


def _river_index(db: Session) -> dict[tuple[int, str], WaterBody]:
    index: dict[tuple[int, str], WaterBody] = {}
    rivers = db.scalars(
        select(WaterBody).where(WaterBody.water_type == WaterBodyType.RIVER)
    )
    for body in rivers:
        if body.state_id is None:
            continue
        # Strip the "(State)" qualifier the platform adds to disambiguate.
        plain = body.name.split("(")[0]
        index.setdefault((body.state_id, _river_key(plain)), body)
    return index


def import_prs_csv(
    db: Session,
    path: Path,
    *,
    source: str,
    assessment_year: int,
    source_reference: str,
) -> ImportReport:
    """Replace one assessment's classifications with the file's contents.

    Idempotent per (source, assessment year): re-importing a corrected file
    replaces the earlier rows rather than adding to them.
    """
    if not source_reference.strip():
        raise ValueError("source_reference is required: say where the file came from.")
    report = ImportReport()
    states = {normalise_name(s.name): s for s in db.scalars(select(State))}
    rivers = _river_index(db)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"missing required column(s): {', '.join(missing)}")
        rows = list(reader)

    db.execute(
        delete(SourceClassification).where(
            SourceClassification.source == source,
            SourceClassification.assessment_year == assessment_year,
            SourceClassification.classification_type == PRS_TYPE,
        )
    )
    for n, row in enumerate(rows, start=2):  # header is line 1
        report.rows += 1
        state_name = (row.get("state") or "").strip()
        river = (row.get("river") or "").strip()
        priority = (row.get("priority") or "").strip().upper()
        if not state_name or not river:
            report.rejected.append(f"line {n}: state and river are required")
            continue
        if priority not in PRIORITIES:
            report.rejected.append(f"line {n}: priority {priority!r} is not I-V")
            continue
        bod_text = (row.get("bod_max_mg_l") or "").strip()
        if bod_text:
            try:
                bod = float(bod_text)
            except ValueError:
                report.rejected.append(
                    f"line {n}: bod_max_mg_l {bod_text!r} is not a number"
                )
                continue
            if bod < 0:
                report.rejected.append(f"line {n}: bod_max_mg_l is negative")
                continue

        state = states.get(normalise_name(state_name))
        body = rivers.get((state.id, _river_key(river))) if state else None
        if body is None:
            report.unmatched.append(f"line {n}: {river} ({state_name})")
        else:
            report.matched += 1
        db.add(
            SourceClassification(
                water_body_id=body.id if body else None,
                source=source,
                classification_type=PRS_TYPE,
                assessment_year=assessment_year,
                river_name=river,
                stretch_name=(row.get("stretch") or "").strip() or None,
                state_name=state_name,
                priority=priority,
                category="Polluted river stretch",
                qualifying_parameter="bod" if bod_text else None,
                qualifying_value=bod_text or None,
                source_reference=f"{source_reference} (line {n})",
                match_method="canonical_name_in_state" if body else "unmatched",
            )
        )
        report.stored += 1
    db.commit()
    return report
