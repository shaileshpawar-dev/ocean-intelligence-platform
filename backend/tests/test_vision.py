"""Tests for the detector layer.

Most of these encode the scientific-integrity requirements directly: the SAR
detector must refuse claims C-band cannot support, must distinguish structured
dark patches from uniformly dark low-wind cells, and must never assert an
implausibly large slick.
"""

from __future__ import annotations

import pytest
from app.models.enums import DetectionMethod, EvidenceLevel, PollutionSignature
from app.vision.base import BaseDetector, Detection
from app.vision.mock_detector import MockDetector
from app.vision.sar_detector import (
    MAX_HEURISTIC_CONFIDENCE,
    MAX_PLAUSIBLE_SLICK_KM2,
    SARDarkFormationDetector,
    estimate_dark_fraction,
)
from app.vision.yolo_detector import (
    DEFAULT_CLASS_MAP,
    LABEL_SIGNATURE_MAP,
    YOLODetector,
)


@pytest.fixture
def detector() -> SARDarkFormationDetector:
    return SARDarkFormationDetector(threshold_db=-22.0)


def cell(mean: float, p10: float, p90: float, area_km2: float = 1000.0, **extra) -> dict:
    """Build a detector input for one cell."""
    return {
        "region_code": "test_cell",
        "mean_db": mean,
        "p10_db": p10,
        "p90_db": p90,
        "stddev_db": 3.0,
        "latitude": 25.0,
        "longitude": 55.0,
        "area_km2": area_km2,
        **extra,
    }


class TestNegativeResults:
    def test_bright_ocean_yields_explicit_no_anomaly(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """An unremarkable cell returns a negative, not an empty list.

        An explicit negative is data: it says the cell was looked at.
        """
        result = detector.predict(cell(mean=-10.0, p10=-14.0, p90=-6.0))
        assert len(result) == 1
        assert result[0].signature is PollutionSignature.NO_ANOMALY

    def test_missing_statistics_returns_nothing(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """No data means no claim, not a default claim."""
        assert detector.predict({"region_code": "x", "mean_db": -15.0}) == []


class TestDarkFormationDiscrimination:
    def test_structured_dark_patch_is_oil_like(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """Dark tail against a normal-brightness sea: the slick signature."""
        result = detector.predict(cell(mean=-14.0, p10=-30.0, p90=-9.0))
        assert result[0].signature is PollutionSignature.OIL_LIKE_SIGNATURE

    def test_uniformly_dark_cell_is_not_called_oil(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """Uniform darkness is a low-wind sea state, not a localised film.

        This is the single most important discrimination the detector makes.
        """
        result = detector.predict(cell(mean=-25.0, p10=-26.0, p90=-24.0))
        assert result[0].signature is PollutionSignature.DARK_FORMATION
        assert any("uniformly dark" in c.lower() for c in result[0].caveats)

    def test_darker_patch_scores_higher(self, detector: SARDarkFormationDetector) -> None:
        shallow = detector.predict(cell(mean=-14.0, p10=-23.0, p90=-9.0))[0]
        deep = detector.predict(cell(mean=-14.0, p10=-32.0, p90=-9.0))[0]
        assert deep.confidence > shallow.confidence


class TestWindDisambiguation:
    def test_low_wind_halves_confidence_and_warns(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """Below ~3 m/s a dark patch is not separable from the background."""
        windy = detector.predict(
            cell(mean=-14.0, p10=-30.0, p90=-9.0, wind_speed_ms=12.0)
        )[0]
        calm = detector.predict(cell(mean=-14.0, p10=-30.0, p90=-9.0, wind_speed_ms=1.0))[
            0
        ]
        assert calm.confidence < windy.confidence
        assert any("wind speed" in c.lower() for c in calm.caveats)


class TestPlausibilityGate:
    def test_implausibly_large_dark_region_is_downgraded(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """A dark area larger than any recorded slick cannot be called oil.

        This is the guardrail that stops the platform reporting a 78,000 km
        squared "oil spill" that is really a wind field.
        """
        huge = detector.predict(
            cell(mean=-14.0, p10=-30.0, p90=-9.0, area_km2=800_000.0)
        )[0]
        assert huge.estimated_area_km2 > MAX_PLAUSIBLE_SLICK_KM2
        assert huge.signature is PollutionSignature.DARK_FORMATION
        assert huge.extra["downgrade_reason"] == "implausible_extent"

    def test_plausible_area_keeps_oil_like_claim(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """The same signature at slick-plausible scale survives the gate."""
        small = detector.predict(cell(mean=-14.0, p10=-30.0, p90=-9.0, area_km2=2_000.0))[
            0
        ]
        assert small.estimated_area_km2 < MAX_PLAUSIBLE_SLICK_KM2
        assert small.signature is PollutionSignature.OIL_LIKE_SIGNATURE

    def test_downgrade_reduces_confidence(
        self, detector: SARDarkFormationDetector
    ) -> None:
        small = detector.predict(cell(mean=-14.0, p10=-30.0, p90=-9.0, area_km2=2_000.0))[
            0
        ]
        huge = detector.predict(
            cell(mean=-14.0, p10=-30.0, p90=-9.0, area_km2=800_000.0)
        )[0]
        assert huge.confidence < small.confidence


class TestHonestyContract:
    def test_confidence_is_never_presented_as_calibrated(
        self, detector: SARDarkFormationDetector
    ) -> None:
        for stats in [
            cell(mean=-10.0, p10=-14.0, p90=-6.0),
            cell(mean=-14.0, p10=-30.0, p90=-9.0),
            cell(mean=-25.0, p10=-26.0, p90=-24.0),
        ]:
            assert detector.predict(stats)[0].confidence_is_calibrated is False

    def test_heuristic_confidence_is_capped(
        self, detector: SARDarkFormationDetector
    ) -> None:
        """A rule-based score must never claim near-certainty."""
        extreme = detector.predict(
            cell(mean=-14.0, p10=-60.0, p90=0.0, area_km2=1_000.0)
        )[0]
        assert extreme.confidence <= MAX_HEURISTIC_CONFIDENCE

    def test_lookalike_caveat_always_attached_to_positive_claims(
        self, detector: SARDarkFormationDetector
    ) -> None:
        result = detector.predict(cell(mean=-14.0, p10=-30.0, p90=-9.0))[0]
        assert any(
            "look" in c.lower() or "not unique to oil" in c.lower()
            for c in result.caveats
        )

    def test_resolution_caveat_attached(self, detector: SARDarkFormationDetector) -> None:
        """Consumers must know this screens cells, it does not delineate."""
        result = detector.predict(cell(mean=-14.0, p10=-30.0, p90=-9.0))[0]
        assert any("does not delineate" in c for c in result.caveats)


class TestSignatureGuardrail:
    def test_detector_rejects_unsupported_signature(self) -> None:
        """A SAR detector must not be able to emit an optical-only class.

        This guardrail is what would have prevented the original system from
        labelling C-band backscatter as 'plastic_waste'.
        """

        class RogueSARDetector(SARDarkFormationDetector):
            def predict(self, payload, **kwargs):
                return self._validate(
                    [
                        Detection(
                            signature=PollutionSignature.PLASTIC_DEBRIS_SIGNATURE,
                            confidence=0.9,
                            method=DetectionMethod.SAR_DARK_FORMATION,
                            model_version="rogue",
                        )
                    ]
                )

        with pytest.raises(ValueError, match="unsupported signature"):
            RogueSARDetector().predict(cell(mean=-14.0, p10=-30.0, p90=-9.0))

    def test_sar_cannot_claim_optical_only_signatures(
        self, detector: SARDarkFormationDetector
    ) -> None:
        assert (
            PollutionSignature.PLASTIC_DEBRIS_SIGNATURE
            not in detector.supported_signatures
        )
        assert (
            PollutionSignature.ALGAE_BLOOM_SIGNATURE not in detector.supported_signatures
        )


class TestDarkFractionEstimation:
    def test_threshold_below_p10_gives_bottom_decile(self) -> None:
        assert (
            estimate_dark_fraction(p10_db=-20.0, p90_db=-8.0, threshold_db=-25.0) == 0.10
        )

    def test_threshold_above_p90_gives_everything(self) -> None:
        assert (
            estimate_dark_fraction(p10_db=-30.0, p90_db=-25.0, threshold_db=-22.0) == 1.0
        )

    def test_interpolates_between_anchors(self) -> None:
        fraction = estimate_dark_fraction(p10_db=-30.0, p90_db=-10.0, threshold_db=-20.0)
        assert 0.10 < fraction < 1.0

    @pytest.mark.parametrize(
        ("p10", "p90", "threshold"),
        [(-30.0, -10.0, -22.0), (-20.0, -20.0, -22.0), (-5.0, -1.0, -22.0)],
    )
    def test_always_a_valid_fraction(
        self, p10: float, p90: float, threshold: float
    ) -> None:
        assert 0.0 <= estimate_dark_fraction(p10, p90, threshold) <= 1.0


class TestMockDetector:
    def test_output_is_deterministic(self) -> None:
        mock = MockDetector()
        assert [d.to_dict() for d in mock.predict("image.png")] == [
            d.to_dict() for d in mock.predict("image.png")
        ]

    def test_every_detection_is_marked_simulated(self) -> None:
        mock = MockDetector()
        for path in ["a.png", "b.png", "c.png", "d.png", "e.png"]:
            for detection in mock.predict(path):
                assert detection.evidence_level is EvidenceLevel.SIMULATED
                assert any("SIMULATED" in c for c in detection.caveats)


class TestDetectorInterface:
    def test_describe_reports_supported_signatures(
        self, detector: SARDarkFormationDetector
    ) -> None:
        described = detector.describe()
        assert described["name"] == "sar-dark-formation"
        assert "oil_like_signature" in described["supported_signatures"]

    def test_base_detector_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            BaseDetector()  # type: ignore[abstract]


class TestYoloClassResolution:
    """Guards the class-map bug inherited from the original notebook.

    The notebook's CLASS_NAMES declared class 3 as 'marine_debris'. The
    actual checkpoint (best.pt, ultralytics 8.4.41) emits
    'chemical_pollution' for class 3, so every class-3 detection in that
    system was reported under the wrong label. The detector now reads the
    names the checkpoint carries.
    """

    def test_checkpoint_names_take_priority_over_the_static_map(self) -> None:
        det = YOLODetector(model_path=None)
        det._names = {
            0: "oil_spill",
            1: "algae_bloom",
            2: "plastic_waste",
            3: "chemical_pollution",
        }
        assert det.resolve_class(3)[0] == "chemical_pollution"

    def test_class_three_is_not_marine_debris(self) -> None:
        """The specific regression."""
        assert DEFAULT_CLASS_MAP[3][0] == "chemical_pollution"
        assert DEFAULT_CLASS_MAP[3][0] != "marine_debris"

    def test_chemical_pollution_degrades_to_surface_anomaly(self) -> None:
        """Optical reflectance cannot identify a chemical species."""
        det = YOLODetector(model_path=None)
        det._names = {3: "chemical_pollution"}
        label, signature = det.resolve_class(3)
        assert label == "chemical_pollution"
        assert signature is PollutionSignature.SURFACE_ANOMALY

    def test_known_labels_map_to_their_signatures(self) -> None:
        det = YOLODetector(model_path=None)
        det._names = {0: "oil_spill", 1: "algae_bloom", 2: "plastic_waste"}
        assert det.resolve_class(0)[1] is PollutionSignature.OIL_LIKE_SIGNATURE
        assert det.resolve_class(1)[1] is PollutionSignature.ALGAE_BLOOM_SIGNATURE
        assert det.resolve_class(2)[1] is PollutionSignature.PLASTIC_DEBRIS_SIGNATURE

    def test_unrecognised_label_degrades_rather_than_guesses(self) -> None:
        """A retrained model with a new class must not be guessed into a claim."""
        det = YOLODetector(model_path=None)
        det._names = {7: "mystery_pollutant"}
        label, signature = det.resolve_class(7)
        assert label == "mystery_pollutant"
        assert signature is PollutionSignature.SURFACE_ANOMALY

    def test_unknown_id_with_no_names_is_explicit(self) -> None:
        det = YOLODetector(model_path=None)
        assert det.resolve_class(99) == ("class_99", PollutionSignature.SURFACE_ANOMALY)

    def test_every_mapped_signature_is_supported_by_the_detector(self) -> None:
        """No entry may emit a signature the guardrail would then reject."""
        det = YOLODetector(model_path=None)
        for signature in LABEL_SIGNATURE_MAP.values():
            assert signature in det.supported_signatures
        for _label, signature in DEFAULT_CLASS_MAP.values():
            assert signature in det.supported_signatures
