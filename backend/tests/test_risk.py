"""Tests for the deterministic risk engine.

The properties asserted here are the ones that make the score defensible:
it is reproducible, its parts sum to the whole, and missing data never
masquerades as low risk.
"""

from __future__ import annotations

import pytest
from app.models.enums import EvidenceLevel, PollutionSignature, Severity
from app.risk.engine import FACTOR_WEIGHTS, RiskEngine
from app.risk.geo import GeographicDataProvider, haversine_km


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


class TestDeterminism:
    def test_same_inputs_give_identical_score(self, engine: RiskEngine) -> None:
        """The engine is pure arithmetic: no randomness, no model calls."""
        kwargs = dict(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.72,
            latitude=25.0,
            longitude=55.0,
            estimated_area_km2=120.0,
            trend_slope=0.4,
        )
        first = engine.assess(**kwargs)
        second = engine.assess(**kwargs)
        assert first.score == second.score
        assert [c.points for c in first.contributions] == [
            c.points for c in second.contributions
        ]


class TestContributionsAreComplete:
    def test_contributions_reconstruct_the_score(self, engine: RiskEngine) -> None:
        """Score must equal awarded/available * 100, exactly."""
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.8,
            latitude=25.0,
            longitude=55.0,
            estimated_area_km2=200.0,
            trend_slope=0.5,
        )
        awarded = sum(c.points for c in result.contributions)
        available = sum(c.max_points for c in result.contributions)
        assert result.score == pytest.approx(awarded / available * 100, abs=0.01)

    def test_all_factors_present_when_all_inputs_given(self, engine: RiskEngine) -> None:
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.8,
            latitude=25.0,
            longitude=55.0,
            estimated_area_km2=200.0,
            trend_slope=0.5,
        )
        assert {c.factor for c in result.contributions} == set(FACTOR_WEIGHTS)
        assert result.missing_factors == []

    def test_every_contribution_has_a_human_readable_detail(
        self, engine: RiskEngine
    ) -> None:
        """The dashboard renders these strings; none may be empty."""
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.6,
            latitude=10.0,
            longitude=70.0,
            estimated_area_km2=50.0,
            trend_slope=0.0,
        )
        for contribution in result.contributions:
            assert contribution.detail.strip()
            assert contribution.evidence_level


class TestMissingDataHandling:
    def test_missing_factors_are_reported_not_zeroed(self, engine: RiskEngine) -> None:
        """Unknown must not be silently treated as zero risk."""
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.9,
        )
        assert "affected_area" in result.missing_factors
        assert "coastal_proximity" in result.missing_factors
        assert "historical_trend" in result.missing_factors
        assert not any(c.factor in result.missing_factors for c in result.contributions)

    def test_partial_assessment_is_not_penalised_into_low_risk(
        self, engine: RiskEngine
    ) -> None:
        """A strong signal with sparse context must still score high.

        Zeroing missing factors would drag this to ~26/100 (35 of 135 points)
        and label a confident oil-like detection LOW. Renormalisation keeps
        it HIGH, which is the safe failure direction.
        """
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=1.0,
        )
        assert result.score == pytest.approx(100.0, abs=0.01)
        assert result.severity is Severity.CRITICAL


class TestOrdering:
    def test_oil_scores_above_generic_anomaly(self, engine: RiskEngine) -> None:
        common = dict(confidence=0.7, latitude=25.0, longitude=55.0)
        oil = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE), **common
        )
        anomaly = engine.assess(
            signature=str(PollutionSignature.SURFACE_ANOMALY), **common
        )
        assert oil.score > anomaly.score

    def test_larger_area_scores_higher(self, engine: RiskEngine) -> None:
        common = dict(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.7,
            latitude=25.0,
            longitude=55.0,
        )
        small = engine.assess(estimated_area_km2=5.0, **common)
        large = engine.assess(estimated_area_km2=400.0, **common)
        assert large.score > small.score

    def test_worsening_trend_scores_higher_than_improving(
        self, engine: RiskEngine
    ) -> None:
        common = dict(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.7,
            latitude=25.0,
            longitude=55.0,
        )
        worsening = engine.assess(trend_slope=1.5, **common)
        improving = engine.assess(trend_slope=-1.0, **common)
        assert worsening.score > improving.score

    def test_no_anomaly_scores_lowest(self, engine: RiskEngine) -> None:
        result = engine.assess(
            signature=str(PollutionSignature.NO_ANOMALY), confidence=0.1
        )
        assert result.severity is Severity.LOW


class TestBounds:
    @pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
    @pytest.mark.parametrize("area", [None, 0.1, 10_000.0])
    def test_score_stays_in_range(
        self, engine: RiskEngine, confidence: float, area: float | None
    ) -> None:
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=confidence,
            latitude=25.0,
            longitude=55.0,
            estimated_area_km2=area,
        )
        assert 0.0 <= result.score <= 100.0

    def test_confidence_is_clamped(self, engine: RiskEngine) -> None:
        """Out-of-range confidence must not push the score past its bound."""
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE), confidence=5.0
        )
        assert result.score <= 100.0


class TestEvidencePropagation:
    def test_simulated_input_yields_simulated_assessment(
        self, engine: RiskEngine
    ) -> None:
        """A risk derived from demo data must never look real."""
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.8,
            evidence_level=EvidenceLevel.SIMULATED,
        )
        assert result.evidence_level is EvidenceLevel.SIMULATED


class TestNarrative:
    def test_narrative_mentions_every_contributing_factor(
        self, engine: RiskEngine
    ) -> None:
        """The explanation is derived from the numbers, so it cannot drift."""
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE),
            confidence=0.7,
            latitude=25.0,
            longitude=55.0,
            estimated_area_km2=100.0,
            trend_slope=0.3,
        )
        for contribution in result.contributions:
            assert contribution.factor in result.narrative

    def test_narrative_flags_partial_assessment(self, engine: RiskEngine) -> None:
        result = engine.assess(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE), confidence=0.7
        )
        assert "renormalised" in result.narrative


class TestGeography:
    def test_haversine_known_distance(self) -> None:
        """London to Paris is ~344 km."""
        assert haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(
            344, abs=5
        )

    def test_proximity_results_carry_precision_notes(self) -> None:
        """Every approximation must state that it is one."""
        geo = GeographicDataProvider()
        coast = geo.distance_to_coast(25.0, 55.0)
        mpa = geo.nearest_protected_area(25.0, 55.0)
        assert coast.precision_note.strip()
        assert mpa.precision_note.strip()
        assert coast.distance_km >= 0
        assert mpa.distance_km >= 0

    def test_nearer_coast_scores_higher_than_open_ocean(self, engine: RiskEngine) -> None:
        """A detection off Dubai should out-score one mid-Pacific."""
        common = dict(
            signature=str(PollutionSignature.OIL_LIKE_SIGNATURE), confidence=0.7
        )
        coastal = engine.assess(latitude=25.2, longitude=55.3, **common)
        open_ocean = engine.assess(latitude=-30.0, longitude=-140.0, **common)
        assert coastal.score > open_ocean.score
