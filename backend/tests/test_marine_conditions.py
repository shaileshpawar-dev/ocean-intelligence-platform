"""Sea conditions: absent is absent, and a model is not an observation.

Two failure modes worth a test. A weather value that goes missing must not
arrive as a zero -- "0.0 m/s wind" and "we do not know the wind" lead to
opposite conclusions about whether a SAR dark formation means anything. And
the low-wind flag must stay tri-state for the same reason: unknown wind is
not calm wind.

Nothing here calls Open-Meteo.
"""

from __future__ import annotations

from app.vision.marine_conditions import (
    ATTRIBUTION,
    EVIDENCE_LEVEL,
    LOW_WIND_MS,
    RegionConditions,
    _as_list,
    _number,
)


def _conditions(**overrides) -> RegionConditions:
    """A complete reading, with fields overridden per test."""
    base = {
        "cell_code": "gulf_of_kutch_w",
        "latitude": 22.35,
        "longitude": 69.15,
        "observed_at": "2026-11-21T10:00",
        "wind_speed_ms": 6.2,
        "wind_direction_deg": 47.0,
        "wind_gust_ms": 8.2,
        "wave_height_m": 0.24,
        "wave_period_s": 14.05,
        "sea_surface_temp_c": 27.2,
    }
    return RegionConditions(**{**base, **overrides})


class TestTheLowWindFlag:
    """Below the threshold a flat sea looks like oil in SAR."""

    def test_calm_water_is_flagged_as_ambiguous(self):
        assert _conditions(wind_speed_ms=LOW_WIND_MS - 0.1).sar_ambiguous is True

    def test_wind_at_the_threshold_is_not_flagged(self):
        assert _conditions(wind_speed_ms=LOW_WIND_MS).sar_ambiguous is False

    def test_unknown_wind_is_unknown_not_calm(self):
        """The distinction the whole flag exists for: no wind reading is not
        evidence of good screening conditions, and must not render as one."""
        assert _conditions(wind_speed_ms=None).sar_ambiguous is None


class TestMissingValues:
    """A gap in the data is a gap, not a zero."""

    def test_a_missing_number_stays_none(self):
        assert _number(None) is None

    def test_an_unparseable_number_is_none_rather_than_zero(self):
        assert _number("calm") is None
        assert _number("") is None

    def test_a_genuine_zero_survives(self):
        """0.0 m/s is a real reading and must not be confused with missing."""
        assert _number(0) == 0.0
        assert _number("0.0") == 0.0

    def test_a_partial_response_leaves_the_other_fields_none(self):
        """Marine endpoint down, wind endpoint up: waves are absent, not flat."""
        payload = _conditions(
            wave_height_m=None, wave_period_s=None, sea_surface_temp_c=None
        ).to_dict()

        assert payload["wind_speed_ms"] == 6.2
        assert payload["wave_height_m"] is None
        assert payload["sea_surface_temp_c"] is None


class TestTheResponseShape:
    """Open-Meteo returns an object for one location and an array for many."""

    def test_a_single_location_object_is_normalised_to_a_list(self):
        assert _as_list({"latitude": 22.3}) == [{"latitude": 22.3}]

    def test_an_array_passes_through(self):
        assert len(_as_list([{"latitude": 22.3}, {"latitude": 15.5}])) == 2

    def test_anything_else_is_empty_rather_than_an_error(self):
        assert _as_list(None) == []
        assert _as_list("unavailable") == []


class TestProvenance:
    """A model analysis is not a satellite observation."""

    def test_conditions_are_inferred_not_observed(self):
        """Open-Meteo serves numerical weather prediction output. Labelling it
        OBSERVED because it is accurate would empty the word of meaning."""
        assert EVIDENCE_LEVEL == "INFERRED"
        assert _conditions().to_dict()["evidence_level"] == "INFERRED"

    def test_every_reading_names_the_provider(self):
        payload = _conditions().to_dict()

        assert payload["provider"] == "Open-Meteo"
        assert payload["attribution"] == ATTRIBUTION
        assert "Open-Meteo" in ATTRIBUTION
