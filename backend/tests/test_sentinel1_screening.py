"""Screening Sentinel-1: counting answers is not counting findings.

The v2.2 model is a scene classifier. It returns one ``Detection`` per tile
whose ``signature`` is the class it chose -- ``no_anomaly`` or
``oil_like_signature``. So "a detection came back" means "the model
answered", not "the model found oil".

The first version of the screening script counted the former. It reported
**24 candidates out of 24 tiles** on a run where the model had in fact
answered ``no_anomaly`` every single time. A 100% hit rate is the kind of
number that gets repeated, and it was exactly backwards.

The saturation check is the other half. A model whose every output is 1.000
is not confident, it is off its training distribution, and a run like that
licenses no conclusion in either direction.
"""

from __future__ import annotations

import numpy as np
import pytest
from app.models.enums import PollutionSignature


def _count_candidates(detections) -> int:
    """The counting rule the script uses, isolated for test.

    Mirrors ``screen_sentinel1.main``: a tile is a candidate only when the
    classifier chose something other than ``no_anomaly``.
    """
    return sum(1 for d in detections if d.signature != PollutionSignature.NO_ANOMALY)


class _Detection:
    """Just enough of a Detection to exercise the counting rule."""

    def __init__(self, signature, confidence: float) -> None:
        self.signature = signature
        self.confidence = confidence


class TestCountingCandidates:
    """An answer of "no" is still an answer."""

    def test_a_no_anomaly_answer_is_not_a_candidate(self):
        """The bug: this returned 1, so every screened tile scored a hit."""
        answered_no = [_Detection(PollutionSignature.NO_ANOMALY, 1.0)]

        assert len(answered_no) == 1, "the classifier does answer every tile"
        assert _count_candidates(answered_no) == 0

    def test_an_oil_like_answer_is_a_candidate(self):
        answered_yes = [_Detection(PollutionSignature.OIL_LIKE_SIGNATURE, 0.77)]

        assert _count_candidates(answered_yes) == 1

    def test_a_full_sweep_of_negatives_counts_zero(self):
        """The real run: 30 tiles, 30 answers, 0 candidates."""
        sweep = [_Detection(PollutionSignature.NO_ANOMALY, 1.0) for _ in range(30)]

        assert _count_candidates(sweep) == 0

    def test_a_tile_the_model_refused_contributes_nothing(self):
        assert _count_candidates([]) == 0


class TestSaturationIsNotConfidence:
    """Every output at 1.000 means the input is unlike the training data."""

    def test_the_real_run_is_recognised_as_saturated(self):
        from scripts_screen_sentinel1 import SATURATED_ABOVE

        confidences = [1.0] * 30

        assert all(c >= SATURATED_ABOVE for c in confidences)

    def test_in_distribution_scores_are_not_saturated(self):
        """Measured on this model's own training patches: 0.005 to 0.83."""
        from scripts_screen_sentinel1 import SATURATED_ABOVE

        observed = [0.0099, 0.0183, 0.0048, 0.7427, 0.5569, 0.8318]

        assert not any(c >= SATURATED_ABOVE for c in observed)


class TestTheNodataMask:
    """Outside a scene footprint there is no backscatter to classify."""

    def test_an_all_nodata_tile_is_rejected(self):
        """VV is zero outside the footprint, and 10*log10(0) is -inf. A tile
        of those must not reach the model, or it produces a confident
        prediction about a part of the world the satellite did not see."""
        from scripts_screen_sentinel1 import stretch

        assert stretch(np.full((224, 224), -np.inf, dtype=np.float32)) is None

    def test_a_mostly_empty_tile_is_rejected(self):
        from scripts_screen_sentinel1 import MIN_VALID_FRACTION, stretch

        tile = np.full((224, 224), -np.inf, dtype=np.float32)
        keep = int(224 * 224 * (MIN_VALID_FRACTION - 0.1))
        tile.flat[:keep] = np.linspace(-25.0, -5.0, keep)

        assert stretch(tile) is None

    def test_a_full_tile_is_stretched_into_the_eight_bit_range(self):
        from scripts_screen_sentinel1 import stretch

        tile = np.linspace(-25.0, -5.0, 224 * 224).reshape(224, 224).astype(np.float32)
        out = stretch(tile)

        assert out is not None
        assert out.dtype == np.uint8
        assert out.min() == 0 and out.max() == 255

    def test_a_flat_tile_is_rejected_rather_than_divided_by_zero(self):
        from scripts_screen_sentinel1 import stretch

        assert stretch(np.full((224, 224), -12.0, dtype=np.float32)) is None


@pytest.fixture(autouse=True, scope="module")
def _import_script():
    """Make the screening script importable under a module name.

    It lives in ``scripts/`` and is written to be run, not imported, so the
    pure functions are reached through an explicit module load rather than
    by putting ``scripts`` on the path for the whole suite.
    """
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "screen_sentinel1.py"
    spec = importlib.util.spec_from_file_location("scripts_screen_sentinel1", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scripts_screen_sentinel1"] = module
    spec.loader.exec_module(module)
    yield
    sys.modules.pop("scripts_screen_sentinel1", None)
