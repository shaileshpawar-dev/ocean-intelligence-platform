"""Source classifications: the only way POLLUTED_STRETCH can appear.

Rows in these CSV fixtures are test data, not CPCB assessments.
"""

from __future__ import annotations

import pytest
from app.models.water import WaterBody
from app.models.water_geo import SourceClassification
from app.services import water_service as ws
from app.water.classifications import import_prs_csv
from sqlalchemy import func, select
from test_water_pipeline import water_db  # noqa: F401  (fixture)

REF = "Test fixture, not a CPCB publication"


def _csv(tmp_path, text: str):
    path = tmp_path / "prs.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TestPrsImport:
    def test_no_classification_means_no_polluted_stretch(self, water_db):  # noqa: F811
        db, _ = water_db
        mithi = db.scalar(select(WaterBody).where(WaterBody.slug == "mithi-river"))
        result = ws.compute_status(db, mithi, as_of_observation=True)
        assert str(result.status) == "HIGH_CONCERN"

    def test_matched_row_changes_status_with_provenance(self, water_db, tmp_path):  # noqa: F811
        db, _ = water_db
        path = _csv(
            tmp_path,
            "state,river,stretch,priority,bod_max_mg_l\n"
            "Maharashtra,Mithi,Test stretch,I,40\n",
        )
        report = import_prs_csv(
            db, path, source="CPCB", assessment_year=2025, source_reference=REF
        )
        assert report.matched == 1 and not report.unmatched and not report.rejected
        mithi = db.scalar(select(WaterBody).where(WaterBody.slug == "mithi-river"))
        result = ws.compute_status(db, mithi, as_of_observation=True)
        assert str(result.status) == "POLLUTED_STRETCH"
        payload = result.to_dict()
        c = payload["source_classifications"][0]
        assert c["evidence_type"] == "SOURCE_CLASSIFICATION"
        assert c["priority"] == "I" and c["assessment_year"] == 2025
        assert REF in c["source_reference"]

    def test_same_name_in_another_state_is_not_matched(self, water_db, tmp_path):  # noqa: F811
        db, _ = water_db
        path = _csv(tmp_path, "state,river,priority\nGujarat,Mithi,II\n")
        report = import_prs_csv(
            db, path, source="CPCB", assessment_year=2025, source_reference=REF
        )
        assert report.matched == 0
        assert report.unmatched == ["line 2: Mithi (Gujarat)"]
        row = db.scalar(select(SourceClassification))
        assert row.water_body_id is None and row.match_method == "unmatched"

    def test_invalid_rows_are_rejected_with_line_numbers(self, water_db, tmp_path):  # noqa: F811
        db, _ = water_db
        path = _csv(
            tmp_path,
            "state,river,priority,bod_max_mg_l\n"
            "Maharashtra,Mithi,VI,\n"
            "Maharashtra,Mithi,I,high\n"
            ",Mithi,I,\n",
        )
        report = import_prs_csv(
            db, path, source="CPCB", assessment_year=2025, source_reference=REF
        )
        assert report.stored == 0
        assert [r.split(":")[0] for r in report.rejected] == [
            "line 2",
            "line 3",
            "line 4",
        ]

    def test_reimport_replaces_the_assessment(self, water_db, tmp_path):  # noqa: F811
        db, _ = water_db
        path = _csv(tmp_path, "state,river,priority\nMaharashtra,Mithi,III\n")
        for _ in range(2):
            import_prs_csv(
                db, path, source="CPCB", assessment_year=2025, source_reference=REF
            )
        assert db.scalar(select(func.count(SourceClassification.id))) == 1

    def test_missing_columns_and_reference_are_refused(self, water_db, tmp_path):  # noqa: F811
        db, _ = water_db
        with pytest.raises(ValueError, match="priority"):
            import_prs_csv(
                db,
                _csv(tmp_path, "state,river\nMaharashtra,Mithi\n"),
                source="CPCB",
                assessment_year=2025,
                source_reference=REF,
            )
        with pytest.raises(ValueError, match="source_reference"):
            import_prs_csv(
                db,
                _csv(tmp_path, "state,river,priority\n"),
                source="CPCB",
                assessment_year=2025,
                source_reference=" ",
            )
