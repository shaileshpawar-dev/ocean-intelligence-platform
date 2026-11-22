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


class TestTheDocumentedRebuildCommandExists:
    """The report tells a reader to run a script. It has to be there.

    A documented command that does not exist is worse than an undocumented
    one: the reader trusts it, runs it, and concludes the whole report is
    decorative.
    """

    @staticmethod
    def _script() -> str:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "rebuild_candidate_optical.py"
        )
        assert path.exists(), f"{path.name} is documented in the report"
        return path.read_text(encoding="utf-8")

    def test_the_report_and_the_script_agree_on_the_flag(self):
        """``--limit`` is the flag the report prints."""
        from pathlib import Path

        report = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "FINAL_STATUS_REPORT.md"
        ).read_text(encoding="utf-8")
        assert "scripts/rebuild_candidate_optical.py --limit 25" in report
        assert '"--limit"' in self._script()

    def test_it_reports_a_missing_scene_rather_than_inventing_one(self):
        """No synthetic fallback, and the absent case is counted, not hidden."""
        source = self._script()

        assert "NoOpticalSceneError" in source
        assert "np.random" not in source
        assert "absent" in source


class TestTheSARPatchImageIsReachable:
    """The patch image is real. It has to actually be served.

    ``REPO_ROOT`` is ``/`` inside the container, so a path built from it
    pointed at a ``/data`` that does not exist there -- the fourth time that
    trap has bitten. The page captioned a 256x256 VV patch and served a 404
    for every candidate.
    """

    def test_the_directory_is_configurable_not_repo_anchored(self):
        from app.core.config import Settings

        assert "sar_training_dir" in Settings.model_fields

    def test_an_absolute_setting_is_used_as_given(self, tmp_path, monkeypatch):
        """Not joined under the repo root, which is what the image relies on.

        The absolute path comes from ``tmp_path`` rather than a literal:
        ``/app/...`` is not absolute on Windows, where this suite also runs,
        so a hardcoded POSIX path would assert the opposite of the intent.
        """
        import importlib

        from app.core.config import settings

        target = tmp_path / "sar_oil_v2"
        monkeypatch.setattr(settings, "sar_training_dir", str(target))
        module = importlib.import_module("app.services.candidate_service")

        assert module._training_dir() == target

    def test_a_relative_setting_is_anchored_on_the_repo_root(self, monkeypatch):
        """The development default, where the repo root is the real root."""
        import importlib

        from app.core.config import REPO_ROOT, settings

        monkeypatch.setattr(
            settings, "sar_training_dir", "data/training/sar_oil_v2"
        )
        module = importlib.import_module("app.services.candidate_service")

        assert module._training_dir() == REPO_ROOT / "data/training/sar_oil_v2"

    def test_the_image_env_var_is_set_in_the_runtime_stage(self):
        """Set in the Dockerfile beside the other two for the same reason."""
        from pathlib import Path

        dockerfile = (
            Path(__file__).resolve().parents[2]
            / "docker"
            / "Dockerfile.backend"
        ).read_text(encoding="utf-8")

        assert 'SAR_TRAINING_DIR="/app/data/training/sar_oil_v2"' in dockerfile

    def test_a_missing_file_is_stated_rather_than_hidden(self):
        """Hiding the image left its caption describing nothing."""
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "CandidateReview.tsx"
        ).read_text(encoding="utf-8")

        assert "patchImageMissing" in page
        assert "Patch image not on disk" in page
        assert 'style.display = "none"' not in page


class TestNoPanelStillCallsRealDataSimulated:
    """A stale 'simulated' label on real data is the same failure inverted.

    The banner at the top of Candidate Review was corrected for items 1 and
    2, but the four per-product captions under the optical viewer, and the
    narrative the fusion engine writes, still said the pixels were synthetic.
    They are measured Sentinel-2 L2A reflectance.
    """

    @staticmethod
    def _page() -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "CandidateReview.tsx"
        ).read_text(encoding="utf-8")

    def test_the_product_captions_no_longer_claim_simulation(self):
        page = self._page()

        assert "Simulated True-Colour RGB" not in page
        assert "Simulated SWIR Composite" not in page
        assert "Simulated Scene Classification" not in page
        assert "Simulated NDCI Index" not in page
        assert "measured Sentinel-2 L2A surface reflectance" in page

    def test_the_page_banner_names_what_is_actually_modelled(self):
        """Drift and shoreline contact; not optical, not vessels."""
        page = self._page()

        assert "Optical, AIS and drift panels are synthetic" not in page
        assert "the drift and shoreline-contact panels are model output" in page

    def test_the_page_banner_is_not_headed_simulated_data(self):
        """``SimulatedBanner`` prints that heading, and a crop keeps only it.

        The page-level note and the concordance note describe measured data
        with a caveat, so they are ``ProvenanceNote``. The two that remain
        ``SimulatedBanner`` are genuinely model output: the particle drift
        track and the demonstration receptor screening.
        """
        page = self._page()
        banners = page.count("<SimulatedBanner")

        assert banners == 2, f"expected drift and impact only, found {banners}"
        assert "<ProvenanceNote>Research replay over a frozen historical" in page
        assert "<ProvenanceNote>Rule-based concordance" in page

    def test_the_fusion_narrative_does_not_call_the_pixels_synthetic(self):
        import inspect

        from app.vision import multi_sensor

        source = inspect.getsource(multi_sensor)

        assert "These pixels are synthetic" not in source
        assert "Simulated Sentinel-2 optical product" not in source
