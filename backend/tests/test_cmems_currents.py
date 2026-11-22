"""Currents: the convention, and never passing a placeholder off as a field.

Two risks worth pinning.

A current vector has a direction, and there are two conventions for stating
it. Oceanographers give the bearing water flows *toward*; meteorologists give
the bearing wind comes *from*. They differ by 180 degrees, which in a drift
simulation is the difference between oil reaching the shore and oil heading
out to sea. The drift engine expects the oceanographic convention, so that is
what ``CurrentReading.direction_deg`` returns, and it is asserted here rather
than left to a comment.

And the engine has always had a default current of 0.22 m/s due east. A track
drawn from that constant looks exactly like a track drawn from a real field.
The source string is what distinguishes them afterwards, so a run that fell
back must say so.

No test here calls Copernicus.
"""

from __future__ import annotations

import math

import pytest
from app.vision.cmems_client import (
    CHLOROPHYLL_EVIDENCE,
    CURRENTS_EVIDENCE,
    ChlorophyllReading,
    CurrentReading,
)


def _current(u: float, v: float) -> CurrentReading:
    return CurrentReading(cell_code="gulf_of_mannar", valid_on="2026-11-21", u_ms=u, v_ms=v)


class TestTheDirectionConvention:
    """Bearing the water flows toward, clockwise from north."""

    @pytest.mark.parametrize(
        ("u", "v", "expected", "heading"),
        [
            (0.0, 1.0, 0.0, "northward"),
            (1.0, 0.0, 90.0, "eastward"),
            (0.0, -1.0, 180.0, "southward"),
            (-1.0, 0.0, 270.0, "westward"),
        ],
    )
    def test_cardinal_flows_give_the_expected_bearing(self, u, v, expected, heading):
        assert _current(u, v).direction_deg == pytest.approx(expected), heading

    def test_a_northeast_flow_reads_as_forty_five_degrees(self):
        assert _current(1.0, 1.0).direction_deg == pytest.approx(45.0)

    def test_the_bearing_is_toward_not_from(self):
        """The 180-degree error this test exists to catch: water moving east
        is 90 degrees, not 270. Getting it backwards would send every drift
        track the wrong way while still looking entirely plausible."""
        eastward = _current(1.0, 0.0)

        assert eastward.direction_deg == pytest.approx(90.0)
        assert eastward.direction_deg != pytest.approx(270.0)

    def test_the_bearing_is_always_in_range(self):
        for angle in range(0, 360, 17):
            radians = math.radians(angle)
            reading = _current(math.sin(radians), math.cos(radians))
            assert 0.0 <= reading.direction_deg < 360.0


class TestSpeed:
    """Magnitude of the vector, in metres per second."""

    def test_speed_is_the_vector_magnitude(self):
        assert _current(0.3, 0.4).speed_ms == pytest.approx(0.5)

    def test_still_water_is_zero_not_missing(self):
        assert _current(0.0, 0.0).speed_ms == 0.0


class TestTheFallbackIsLabelled:
    """A placeholder current must never be mistaken for a modelled one.

    Resolution runs cache first, then a live read, then the placeholder, so
    each test disables the layers above the one it is exercising.
    """

    @staticmethod
    def _no_cache(monkeypatch):
        monkeypatch.setattr(
            "app.services.drift_service._nearest_cached_current", lambda *a: None
        )

    def test_an_unavailable_field_falls_back_and_says_so(self, monkeypatch):
        from app.services import drift_service

        self._no_cache(monkeypatch)
        monkeypatch.setattr(
            "app.vision.cmems_client.CMEMSClient.fetch_current",
            lambda *a, **k: None,
        )

        speed, direction, source = drift_service._resolve_current(21.0, 69.0)

        assert speed == drift_service.PLACEHOLDER_CURRENT_MS
        assert direction == drift_service.PLACEHOLDER_CURRENT_DEG
        assert "placeholder" in source.lower()

    def test_a_live_field_names_the_product_and_its_date(self, monkeypatch):
        from app.services import drift_service

        self._no_cache(monkeypatch)
        monkeypatch.setattr(
            "app.vision.cmems_client.CMEMSClient.fetch_current",
            lambda *a, **k: _current(0.1, 0.1),
        )

        speed, direction, source = drift_service._resolve_current(9.0, 79.0)

        assert speed == pytest.approx(math.hypot(0.1, 0.1))
        assert direction == pytest.approx(45.0)
        assert "placeholder" not in source.lower()
        assert "2026-11-21" in source

    def test_a_cached_regional_current_is_preferred_to_a_live_call(
        self, monkeypatch
    ):
        """The serving image has no Copernicus toolbox, and a drift request
        must not wait on object storage. Cache first is the whole point."""
        from app.services import drift_service

        called = []
        monkeypatch.setattr(
            "app.services.drift_service._nearest_cached_current",
            lambda *a: (_current(0.0, 0.3), 0.4, "Gulf of Mannar"),
        )
        monkeypatch.setattr(
            "app.vision.cmems_client.CMEMSClient.fetch_current",
            lambda *a, **k: called.append(1),
        )

        speed, direction, source = drift_service._resolve_current(9.0, 79.0)

        assert speed == pytest.approx(0.3)
        assert direction == pytest.approx(0.0)
        assert not called, "a cached current must not trigger a network read"
        assert "Gulf of Mannar" in source

    def test_a_neighbouring_cell_says_how_far_away_it_was(self, monkeypatch):
        """Another cell's current is an approximation, and the source string
        has to make that a weaker claim than "the current here"."""
        from app.services import drift_service

        monkeypatch.setattr(
            "app.services.drift_service._nearest_cached_current",
            lambda *a: (_current(0.1, 0.0), 63.0, "Palk Bay"),
        )

        _, _, source = drift_service._resolve_current(9.0, 79.0)

        assert "63 km away" in source
        assert "Palk Bay" in source


class TestProvenance:
    """A model analysis and a satellite retrieval are not the same thing."""

    def test_currents_are_inferred(self):
        """An ocean model's analysis, however good, is not a measurement."""
        assert CURRENTS_EVIDENCE == "INFERRED"
        assert _current(0.1, 0.0).to_dict()["evidence_level"] == "INFERRED"

    def test_chlorophyll_is_observed(self):
        """A processed retrieval, but derived from radiance a sensor
        recorded -- unlike the current field, which no instrument saw."""
        assert CHLOROPHYLL_EVIDENCE == "OBSERVED"

    def test_every_reading_credits_copernicus_marine(self):
        current = _current(0.1, 0.0).to_dict()
        chl = ChlorophyllReading(
            cell_code="palk_bay",
            valid_on="2026-11-19",
            chl_mg_m3=0.78,
            valid_pixels=690,
        ).to_dict()

        for payload in (current, chl):
            assert "Copernicus Marine" in payload["attribution"]
            assert payload["product"]
