"""The Candidate Review panels: real pixels, no identities, no fallback.

Three properties that would be easy to lose and hard to notice.

The optical chip must come from Copernicus or not exist. The panel used to
synthesise plausible ocean reflectance when no scene was available, which
meant an absent observation and a real one rendered identically — the worst
possible failure mode for a page whose job is to show what was measured.

The vessel panel must name nobody. It previously marked a fictional vessel
`SOURCE_SUSPECT` at up to 0.97 confidence; these candidates are benchmark
patches where no release was established, so an attribution would be an
accusation about something that did not happen.

And a severity word has to carry its meaning. "CRITICAL" beside a
statistical anomaly reads as a confirmed emergency unless told otherwise.
"""

from __future__ import annotations

import inspect

import pytest
from app.vision import cog_extractor
from app.vision.cog_extractor import COGExtractor


class TestTheOpticalChipIsRealOrAbsent:
    """No synthetic fallback remains anywhere in the path."""

    def test_the_synthetic_band_generator_is_gone(self):
        """It is not deprecated or unused — it is removed. An unused
        generator is one call away from being used again."""
        assert not hasattr(COGExtractor, "_generate_calibrated_ocean_bands")

    def test_nothing_in_the_module_generates_reflectance(self):
        source = inspect.getsource(cog_extractor)

        for banned in ("default_rng", "np.random", "wave_pattern"):
            assert banned not in source, f"{banned} still present"

    def test_a_missing_scene_raises_rather_than_substituting(self):
        """The exception exists so the caller must handle the absence."""
        assert issubclass(COGExtractor.NoUsableScene, Exception)

        source = inspect.getsource(COGExtractor._fetch_real_bands)
        assert source.count("raise self.NoUsableScene") >= 4

    def test_the_temporal_window_is_five_days(self):
        """Beyond about one revisit a scene describes different water: a
        slick moves, disperses and weathers within days."""
        assert COGExtractor.MAX_TEMPORAL_OFFSET_DAYS == 5

    def test_every_band_needed_for_the_indices_is_requested(self):
        """NDCI needs B05/B04, NDTI needs B04/B03, FDI needs B08/B06/B11.
        A band quietly dropped would make an index silently wrong."""
        for band in ("B02", "B03", "B04", "B05", "B08", "B11"):
            assert band in COGExtractor.BANDS, band

    def test_an_empty_chip_is_treated_as_no_scene(self):
        """All-zero means outside the footprint, not very dark water —
        which would read as a perfectly calm, perfectly black sea."""
        source = inspect.getsource(COGExtractor._fetch_real_bands)

        assert "does not cover this position" in source

    def test_the_tar_accept_header_is_sent(self):
        """Without it the API returns only the first output and the other
        six bands are silently dropped."""
        source = inspect.getsource(COGExtractor._fetch_real_bands)

        assert "application/tar" in source


class TestTheVesselPanelNamesNobody:
    """Aggregate activity, never an attribution."""

    def test_candidate_activity_returns_counts_not_identities(self):
        from app.vision.gfw_client import RegionActivity, candidate_activity

        source = inspect.getsource(candidate_activity)
        for identifier in ("mmsi", "imo", "callsign", "shipname"):
            assert identifier not in source.lower(), identifier

        fields = set(RegionActivity.__dataclass_fields__)
        assert "hours_by_flag" in fields
        assert not fields & {"mmsi", "vessel_name", "imo"}

    def test_the_window_is_documented_as_context_not_investigation(self):
        from app.vision import gfw_client

        source = inspect.getsource(gfw_client)
        assert "proximity as causation" in source

    def test_the_radius_and_window_are_deliberately_generous(self):
        """A tight window invites reading proximity as causation."""
        from app.vision.gfw_client import CANDIDATE_RADIUS_KM, CANDIDATE_WINDOW_DAYS

        assert CANDIDATE_RADIUS_KM >= 20
        assert CANDIDATE_WINDOW_DAYS >= 5


class TestSeverityCarriesItsMeaning:
    """A risk score is potential impact, not certainty."""

    def test_the_frontend_defines_the_meaning_once(self):
        """One constant, so a page cannot show the badge without it."""
        ui = (
            pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "components"
            / "ui.tsx"
        ).read_text(encoding="utf-8")

        assert "RISK_MEANING" in ui
        assert "potential impact if confirmed" in ui
        assert "Not a confirmed incident" in ui

    def test_the_badge_carries_it_as_a_tooltip(self):
        ui = (
            pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "components"
            / "ui.tsx"
        ).read_text(encoding="utf-8")
        badge = ui[ui.index("export function RiskBadge") :][:900]

        assert "title={RISK_MEANING}" in badge
