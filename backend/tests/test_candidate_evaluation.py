"""Metric computation for the SAR candidate evaluation panel.

The small cases are worked by hand in the assertions rather than compared
against another implementation, because the point is to catch a formula that
is subtly wrong -- a swapped FP/FN, an ROC walked in the wrong direction --
and checking one implementation against another written the same afternoon
would not.
"""

from __future__ import annotations

import os

import pytest
from app.monitoring.candidate_evaluation import (
    auc_from,
    confusion_at,
    evaluate_candidates,
    roc_curve,
)
from fastapi.testclient import TestClient


class TestConfusionMatrix:
    def test_a_hand_checked_case(self) -> None:
        #  label  score   at t=0.5 -> predicted
        #    1     0.9       +        TP
        #    1     0.6       +        TP
        #    1     0.3       -        FN
        #    0     0.8       +        FP
        #    0     0.2       -        TN
        #    0     0.1       -        TN
        labels = [1, 1, 1, 0, 0, 0]
        scores = [0.9, 0.6, 0.3, 0.8, 0.2, 0.1]
        assert confusion_at(labels, scores, 0.5) == {"tp": 2, "fp": 1, "tn": 2, "fn": 1}

    def test_the_threshold_is_inclusive(self) -> None:
        """A score exactly at the threshold counts as predicted-positive."""
        assert confusion_at([1], [0.5], 0.5)["tp"] == 1
        assert confusion_at([1], [0.5], 0.50001)["fn"] == 1

    def test_threshold_zero_predicts_everything_positive(self) -> None:
        matrix = confusion_at([1, 1, 0, 0], [0.9, 0.1, 0.8, 0.2], 0.0)
        assert matrix == {"tp": 2, "fp": 2, "tn": 0, "fn": 0}


class TestRocAndAuc:
    def test_a_perfect_separation_has_auc_one(self) -> None:
        labels = [1, 1, 0, 0]
        scores = [0.9, 0.8, 0.2, 0.1]
        assert auc_from(roc_curve(labels, scores)) == pytest.approx(1.0)

    def test_a_perfectly_inverted_ranking_has_auc_zero(self) -> None:
        labels = [1, 1, 0, 0]
        scores = [0.1, 0.2, 0.8, 0.9]
        assert auc_from(roc_curve(labels, scores)) == pytest.approx(0.0)

    def test_an_uninformative_score_has_auc_one_half(self) -> None:
        """All scores tied: the curve is the diagonal."""
        labels = [1, 1, 0, 0]
        scores = [0.5, 0.5, 0.5, 0.5]
        assert auc_from(roc_curve(labels, scores)) == pytest.approx(0.5)

    def test_a_hand_checked_intermediate_auc(self) -> None:
        # Ranked: 0.9(+) 0.8(-) 0.7(+) 0.6(-). Of the four positive/negative
        # pairs, the positive outranks the negative in three, so AUC = 0.75.
        labels = [1, 0, 1, 0]
        scores = [0.9, 0.8, 0.7, 0.6]
        assert auc_from(roc_curve(labels, scores)) == pytest.approx(0.75)

    def test_the_curve_starts_at_the_origin_and_ends_at_one_one(self) -> None:
        points = roc_curve([1, 1, 0, 0], [0.9, 0.4, 0.8, 0.1])
        assert (points[0]["fpr"], points[0]["tpr"]) == (0.0, 0.0)
        assert (points[-1]["fpr"], points[-1]["tpr"]) == (1.0, 1.0)

    def test_one_class_only_yields_no_curve(self) -> None:
        """An ROC needs both classes; returning a diagonal would be a lie."""
        assert roc_curve([1, 1, 1], [0.9, 0.5, 0.1]) == []
        assert auc_from([]) is None


@pytest.fixture
def real_db():
    """The Postgres database, or a skip.

    The suite forces DATABASE_URL at its own temp SQLite file (see
    ``conftest.py``), which is what stops tests reaching a real database. These
    cases therefore skip during a normal run and are here to be pointed at the
    real one deliberately.
    """
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        pytest.skip("real database not configured")
    try:
        from app.core.database import SessionLocal
        from sqlalchemy import text

        session = SessionLocal()
        session.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("real database not reachable")
    yield session
    session.close()


class TestAgainstTheRealDatabase:
    """Skipped unless the Postgres database is reachable."""

    def test_every_stored_candidate_is_labelled_and_scored(self, real_db) -> None:
        result = evaluate_candidates(real_db, threshold=0.5)
        assert result["n"] == 306
        assert result["skipped"] == 0
        assert result["positives"] + result["negatives"] == 306

    def test_it_names_the_model_that_produced_the_scores(self, real_db) -> None:
        result = evaluate_candidates(real_db, threshold=0.5)
        assert result["model"] == "sar-oil-slick-v2.2:2.2.0-experimental"
        assert result["scores_are_calibrated"] is False

    def test_the_threshold_moves_the_matrix_in_the_right_direction(
        self, real_db
    ) -> None:
        """Raising the bar can only reduce positives of both kinds."""
        low = evaluate_candidates(real_db, threshold=0.2)["confusion"]
        high = evaluate_candidates(real_db, threshold=0.8)["confusion"]
        assert high["tp"] <= low["tp"]
        assert high["fp"] <= low["fp"]
        assert high["fn"] >= low["fn"]

    def test_auc_does_not_move_with_the_threshold(self, real_db) -> None:
        """It is a property of the ranking, not of where the cut is made."""
        a = evaluate_candidates(real_db, threshold=0.2)["auc"]
        b = evaluate_candidates(real_db, threshold=0.9)["auc"]
        assert a == b


class TestEvaluationEndpoint:
    def test_it_is_not_swallowed_by_the_model_detail_route(
        self, client: TestClient
    ) -> None:
        """/models/{name}/{version} would otherwise match this path."""
        response = client.get("/api/v1/models/sar-candidates/evaluation")
        assert response.status_code == 200
        assert "confusion" in response.json() or response.json()["n"] == 0

    def test_it_rejects_a_threshold_outside_zero_to_one(
        self, client: TestClient
    ) -> None:
        assert (
            client.get(
                "/api/v1/models/sar-candidates/evaluation", params={"threshold": 1.5}
            ).status_code
            == 422
        )

    def test_it_always_states_that_the_scores_are_uncalibrated(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/v1/models/sar-candidates/evaluation").json()
        assert "not been calibrated" in body["note"]
