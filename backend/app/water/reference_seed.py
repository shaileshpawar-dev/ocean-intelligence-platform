"""Mirror the reference catalogue into the ``reference_standards`` tables.

The catalogue module is the reviewed source of truth; the tables make the same
values queryable (and joinable in PostGIS later) without a code import. Seeding
is idempotent: a standard is updated in place by code, and thresholds are
replaced wholesale so a removed limit does not linger.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.water_geo import ReferenceStandard, ReferenceThreshold
from app.water.reference_catalog import ALL_STANDARDS


def seed_reference_standards(db: Session) -> int:
    """Upsert every catalogued standard. Returns the number written."""
    for definition in ALL_STANDARDS:
        row = db.scalar(
            select(ReferenceStandard).where(ReferenceStandard.code == definition.code)
        )
        if row is None:
            row = ReferenceStandard(code=definition.code)
            db.add(row)
        row.name = definition.name
        row.category = definition.category
        row.issuing_body = definition.issuing_body
        row.legal_basis = definition.legal_basis
        row.version = definition.version
        row.effective_date = definition.effective_date
        row.source_url = definition.source_url
        row.verified_note = definition.verified_note
        row.notes = definition.notes or None
        db.flush()
        db.execute(
            delete(ReferenceThreshold).where(ReferenceThreshold.standard_id == row.id)
        )
        for t in definition.thresholds:
            db.add(
                ReferenceThreshold(
                    standard_id=row.id,
                    parameter=t.parameter,
                    threshold_type=t.threshold_type,
                    minimum=t.minimum,
                    maximum=t.maximum,
                    desirable=t.desirable,
                    unit=t.unit,
                    notes=t.note or None,
                )
            )
    db.commit()
    return len(ALL_STANDARDS)
