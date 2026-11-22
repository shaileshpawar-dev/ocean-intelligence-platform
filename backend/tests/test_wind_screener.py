"""Tests for ERA5 wind integration, spatiotemporal collocation, and wind-aware SAR screening."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
import pytest

from app.models.enums import PollutionSignature
from app.vision.base import BaseDetector, Detection
from app.vision.era5_client import (
    CopernicusCDSClient,
    ERA5Record,
    ERA5Service,
    LocalERA5Cache,
    calculate_meteorological_wind_direction,
    calculate_wind_speed,
    haversine_distance_km,
)
from app.vision.multi_sensor import (
    ConcordanceLevel,
    EvidenceConsistency,
    ModalityType,
    MultiSensorIntegrator,
)
from app.vision.wind_screener import (
    ScreeningStatus,
    WindAwareSARScreener,
    WindClassification,
)


class DummyDetector(BaseDetector):
    name = "dummy-detector"
    version = "1.0.0-test"
    supported_signatures = frozenset(
        {
            PollutionSignature.OIL_LIKE_SIGNATURE,
            PollutionSignature.DARK_FORMATION,
            PollutionSignature.NO_ANOMALY,
        }
    )

    def __init__(self, signature: PollutionSignature, confidence: float) -> None:
        self._sig = signature
        self._conf = confidence

    def predict(self, payload: any, **kwargs: any) -> list[Detection]:
        return self._validate(
            [
                Detection(
                    signature=self._sig,
                    confidence=self._conf,
                    confidence_is_calibrated=False,
                    method=self.method,
                    model_version=self.version,
                    class_name=str(self._sig),
                    caveats=["Initial mock caveat"],
                )
            ]
        )


class TestWindCalculations:
    def test_wind_speed_calculation(self) -> None:
        assert calculate_wind_speed(3.0, 4.0) == 5.0
        assert calculate_wind_speed(0.0, 0.0) == 0.0
        assert calculate_wind_speed(-6.0, -8.0) == 10.0

    def test_meteorological_wind_direction(self) -> None:
        # Meteorological convention: direction from which wind blows
        # North wind (blowing from North to South: u=0, v=-5) -> 0° (or 360°)
        assert calculate_meteorological_wind_direction(0.0, -5.0) in (0.0, 360.0)
        # East wind (blowing from East to West: u=-5, v=0) -> 90°
        assert calculate_meteorological_wind_direction(-5.0, 0.0) == 90.0
        # South wind (blowing from South to North: u=0, v=5) -> 180°
        assert calculate_meteorological_wind_direction(0.0, 5.0) == 180.0
        # West wind (blowing from West to East: u=5, v=0) -> 270°
        assert calculate_meteorological_wind_direction(5.0, 0.0) == 270.0

    def test_haversine_distance(self) -> None:
        # Distance between (33.0, 33.0) and (33.25, 33.25)
        d = haversine_distance_km(33.0, 33.0, 33.25, 33.25)
        assert 35.0 < d < 45.0  # Approx 36.8 km


class TestCopernicusCDSClient:
    def test_cds_client_instructions_when_unconfigured(self, monkeypatch) -> None:
        monkeypatch.delenv("CDSAPI_KEY", raising=False)
        monkeypatch.delenv("CDSAPI_URL", raising=False)
        client = CopernicusCDSClient()
        instructions = client.get_instructions()
        assert "https://cds.climate.copernicus.eu" in instructions
        assert ".cdsapirc" in instructions

    def test_missing_api_credentials_does_not_crash(self) -> None:
        client = CopernicusCDSClient()
        assert isinstance(client.is_configured, bool)


class TestERA5CacheAndOfflineBehavior:
    def test_offline_cache_storage_and_retrieval(self, tmp_path) -> None:
        cache_file = tmp_path / "test_cache.json"
        cache = LocalERA5Cache(cache_file)
        assert len(cache) == 0

        rec = ERA5Record(
            source="ECMWF ERA5 Reanalysis Archive",
            dataset_version="reanalysis-era5-single-levels",
            grid_latitude=33.25,
            grid_longitude=33.0,
            acquisition_timestamp_utc="2019-01-31T03:42:57Z",
            sampled_timestamp_utc="2019-01-31T04:00:00Z",
            u10_ms=-1.2,
            v10_ms=4.1,
            wind_speed_ms=4.27,
            wind_direction_deg=163.7,
            temporal_offset_minutes=17.0,
            grid_distance_km=4.8,
            is_coastal=False,
            sampling_method="nearest_grid_linear_time_interp",
            quality_status="reanalysis_available",
        )
        cache.set("test_patch_01.jpg", rec.to_dict())
        cache.save()

        # Reload
        reloaded = LocalERA5Cache(cache_file)
        assert len(reloaded) == 1
        fetched = reloaded.get("test_patch_01.jpg")
        assert fetched is not None
        assert fetched["wind_speed_ms"] == 4.27
        assert fetched["quality_status"] == "reanalysis_available"


class TestWindAwareSARScreener:
    def test_screening_status_within_range(self, tmp_path) -> None:
        cache_file = tmp_path / "test_cache.json"
        cache = LocalERA5Cache(cache_file)
        rec = ERA5Record(
            source="ECMWF ERA5",
            dataset_version="reanalysis-era5-single-levels",
            grid_latitude=33.0,
            grid_longitude=33.0,
            acquisition_timestamp_utc="2019-01-01T00:00:00Z",
            sampled_timestamp_utc="2019-01-01T00:00:00Z",
            u10_ms=3.0,
            v10_ms=4.0,
            wind_speed_ms=5.0,  # 5.0 m/s is within [3, 12]
            wind_direction_deg=180.0,
            temporal_offset_minutes=0.0,
            grid_distance_km=2.0,
            is_coastal=False,
            sampling_method="test",
            quality_status="reanalysis_available",
        )
        cache.set("p_optimal", rec.to_dict())
        cache.save()

        detector = DummyDetector(PollutionSignature.OIL_LIKE_SIGNATURE, 0.85)
        service = ERA5Service(cache_path=cache_file)
        screener = WindAwareSARScreener(detector=detector, era5_service=service)

        res = screener.screen(
            payload={"image": "p_optimal", "latitude": 33.0, "longitude": 33.0},
            patch_id="p_optimal",
        )
        assert res["model_prediction"] == "oil_like_signature"
        assert res["model_confidence"] == 0.85
        assert res["confidence_is_calibrated"] is False  # Confidence remains uncalibrated
        assert res["wind_context"]["classification"] == WindClassification.WITHIN_SCREENING_RANGE.value
        assert res["final_screening_status"] == ScreeningStatus.CANDIDATE_REQUIRES_REVIEW.value
        assert res["retained_for_analyst_review"] is True

    def test_screening_status_low_wind_flag(self, tmp_path) -> None:
        cache_file = tmp_path / "test_cache.json"
        cache = LocalERA5Cache(cache_file)
        rec = ERA5Record(
            source="ECMWF ERA5",
            dataset_version="reanalysis-era5-single-levels",
            grid_latitude=33.0,
            grid_longitude=33.0,
            acquisition_timestamp_utc="2019-01-01T00:00:00Z",
            sampled_timestamp_utc="2019-01-01T00:00:00Z",
            u10_ms=1.0,
            v10_ms=1.0,
            wind_speed_ms=1.41,  # < 3.0 m/s
            wind_direction_deg=225.0,
            temporal_offset_minutes=0.0,
            grid_distance_km=2.0,
            is_coastal=False,
            sampling_method="test",
            quality_status="reanalysis_available",
        )
        cache.set("p_low_wind", rec.to_dict())
        cache.save()

        detector = DummyDetector(PollutionSignature.OIL_LIKE_SIGNATURE, 0.78)
        service = ERA5Service(cache_path=cache_file)
        screener = WindAwareSARScreener(detector=detector, era5_service=service)

        res = screener.screen(
            payload={"image": "p_low_wind"},
            patch_id="p_low_wind",
        )
        # Raw confidence is preserved, not arbitrarily multiplied or halved!
        assert res["model_confidence"] == 0.78
        assert res["wind_context"]["classification"] == WindClassification.LOW_WIND.value
        assert res["final_screening_status"] == ScreeningStatus.LOW_WIND_AMBIGUITY_REVIEW.value
        assert res["retained_for_analyst_review"] is True
        assert any("Low wind speed" in w for w in res["environmental_warnings"])

    def test_screening_status_high_wind_flag(self, tmp_path) -> None:
        cache_file = tmp_path / "test_cache.json"
        cache = LocalERA5Cache(cache_file)
        rec = ERA5Record(
            source="ECMWF ERA5",
            dataset_version="reanalysis-era5-single-levels",
            grid_latitude=33.0,
            grid_longitude=33.0,
            acquisition_timestamp_utc="2019-01-01T00:00:00Z",
            sampled_timestamp_utc="2019-01-01T00:00:00Z",
            u10_ms=10.0,
            v10_ms=10.0,
            wind_speed_ms=14.14,  # > 12.0 m/s
            wind_direction_deg=225.0,
            temporal_offset_minutes=0.0,
            grid_distance_km=2.0,
            is_coastal=False,
            sampling_method="test",
            quality_status="reanalysis_available",
        )
        cache.set("p_high_wind", rec.to_dict())
        cache.save()

        detector = DummyDetector(PollutionSignature.OIL_LIKE_SIGNATURE, 0.65)
        service = ERA5Service(cache_path=cache_file)
        screener = WindAwareSARScreener(detector=detector, era5_service=service)

        res = screener.screen(payload="p_high_wind", patch_id="p_high_wind")
        assert res["wind_context"]["classification"] == WindClassification.HIGH_WIND.value
        assert res["final_screening_status"] == ScreeningStatus.HIGH_WIND_AMBIGUITY_REVIEW.value
        assert res["retained_for_analyst_review"] is True
        assert any("High wind speed" in w for w in res["environmental_warnings"])

    def test_screening_negative_detection(self) -> None:
        detector = DummyDetector(PollutionSignature.NO_ANOMALY, 0.95)
        screener = WindAwareSARScreener(detector=detector)
        res = screener.screen(payload="some_img")
        assert res["final_screening_status"] == ScreeningStatus.NO_CANDIDATE_DETECTED.value
        assert res["retained_for_analyst_review"] is False

    def test_coastal_grid_cell_warning(self, tmp_path) -> None:
        cache_file = tmp_path / "test_cache.json"
        cache = LocalERA5Cache(cache_file)
        rec = ERA5Record(
            source="ECMWF ERA5",
            dataset_version="reanalysis-era5-single-levels",
            grid_latitude=34.0,
            grid_longitude=35.0,
            acquisition_timestamp_utc="2019-01-01T00:00:00Z",
            sampled_timestamp_utc="2019-01-01T00:00:00Z",
            u10_ms=3.0,
            v10_ms=3.0,
            wind_speed_ms=4.24,
            wind_direction_deg=225.0,
            temporal_offset_minutes=0.0,
            grid_distance_km=2.0,
            is_coastal=True,  # Coastal cell
            sampling_method="test",
            quality_status="reanalysis_available",
        )
        cache.set("p_coastal", rec.to_dict())
        cache.save()

        detector = DummyDetector(PollutionSignature.OIL_LIKE_SIGNATURE, 0.70)
        service = ERA5Service(cache_path=cache_file)
        screener = WindAwareSARScreener(detector=detector, era5_service=service)

        res = screener.screen(payload="p_coastal", patch_id="p_coastal", is_coastal=True)
        assert any("Coastal proximity notice" in w for w in res["environmental_warnings"])

    def test_missing_wind_data_preserves_candidate(self, tmp_path) -> None:
        # Provider returns None (offline / network error / missing); missing ERA5 data must NOT delete candidate
        cache_file = tmp_path / "empty_cache.json"
        service = ERA5Service(cache_path=cache_file)
        service.openmeteo_client.fetch_hourly_wind = lambda *a, **kw: None
        detector = DummyDetector(PollutionSignature.OIL_LIKE_SIGNATURE, 0.88)
        screener = WindAwareSARScreener(detector=detector, era5_service=service)

        res = screener.screen(payload="p_unknown", patch_id="p_unknown")
        assert res["model_prediction"] == "oil_like_signature"
        assert res["model_confidence"] == 0.88
        assert res["final_screening_status"] == ScreeningStatus.CANDIDATE_REQUIRES_REVIEW.value
        assert res["retained_for_analyst_review"] is True
        assert any("Wind context unverified" in w for w in res["environmental_warnings"])

    def test_subthreshold_dark_formation_not_promoted(self) -> None:
        # Weak anomaly with confidence < 0.50 should NOT be promoted to an oil candidate
        class SubthresholdDetector(BaseDetector):
            name = "sar-oil-slick-v2.2"
            version = "2.2.0-experimental"
            supported_signatures = frozenset({PollutionSignature.DARK_FORMATION})

            def predict(self, payload: any, **kwargs: any) -> list[Detection]:
                return self._validate(
                    [
                        Detection(
                            signature=PollutionSignature.DARK_FORMATION,
                            confidence=0.35,
                            confidence_is_calibrated=False,
                            method=self.method,
                            model_version=self.version,
                            class_name=str(PollutionSignature.DARK_FORMATION),
                            caveats=["Weak backscatter anomaly"],
                            extra={"p_oil_candidate": 0.35},
                        )
                    ]
                )

        screener = WindAwareSARScreener(detector=SubthresholdDetector())
        res = screener.screen(payload="p_weak")
        assert res["final_screening_status"] == ScreeningStatus.NO_CANDIDATE_DETECTED.value
        assert res["retained_for_analyst_review"] is False


class TestMultiSensorIntegrator:
    """Optical cross-verification of a SAR candidate.

    ``integrate()`` takes the SAR candidate's own fields rather than a packed
    result dict, and reads real Sentinel-2 band metrics rather than booleans
    somebody else already interpreted. These two cases cover the pair that
    matters: chlorophyll that contradicts the oil reading, and a glint
    signature that supports it.
    """

    SAR_TIME = datetime(2019, 1, 1, 2, 0, tzinfo=UTC)

    def test_multi_sensor_conflicting_algae(self) -> None:
        integrator = MultiSensorIntegrator()
        assessment = integrator.integrate(
            candidate_id="target_01",
            latitude=33.0,
            longitude=33.0,
            sar_confidence=0.80,
            screening_status="candidate_requires_review",
            model_version="2.2.0-experimental",
            sar_time=self.SAR_TIME,
            wind_speed_ms=4.5,
            optical_evidence={
                "scene_id": "S2B_MSIL2A_TEST_ALGAE",
                "acquisition_timestamp": self.SAR_TIME.isoformat(),
                "temporal_offset_hours": 0.9,
                "cloud_coverage_fraction": 0.03,
                "valid_water_fraction": 0.97,
                # Elevated chlorophyll-a: the dark patch is a biogenic film.
                "mean_ndci": 0.15,
                "p90_ndci": 0.23,
                "mean_swir_ratio": 0.11,
                "optical_quality_flag": "optimal",
            },
        )
        assert assessment.optical_verification_status == "biogenic_lookalike_confirmed"
        assert assessment.concordance_level == ConcordanceLevel.BIOGENIC_LOOKALIKE
        # The optical reading must be recorded as contradicting the SAR one,
        # not quietly averaged into the score.
        algae_ev = [
            e
            for e in assessment.evidence_items
            if e.modality == ModalityType.OPTICAL_SENTINEL_2
        ]
        assert len(algae_ev) == 1
        assert algae_ev[0].consistency == EvidenceConsistency.CONFLICTING

    def test_multi_sensor_supporting_sunglint(self) -> None:
        integrator = MultiSensorIntegrator()
        assessment = integrator.integrate(
            candidate_id="target_02",
            latitude=33.0,
            longitude=33.0,
            sar_confidence=0.85,
            screening_status="candidate_requires_review",
            model_version="2.2.0-experimental",
            sar_time=self.SAR_TIME,
            wind_speed_ms=5.2,
            optical_evidence={
                "scene_id": "S2B_MSIL2A_TEST_GLINT",
                "acquisition_timestamp": self.SAR_TIME.isoformat(),
                "temporal_offset_hours": 1.1,
                "cloud_coverage_fraction": 0.04,
                "valid_water_fraction": 0.96,
                # Glint contrast with chlorophyll ruled out.
                "mean_ndci": -0.05,
                "p90_ndci": -0.02,
                "mean_swir_ratio": 0.55,
                "optical_quality_flag": "optimal",
            },
        )
        assert assessment.optical_verification_status == "multi_sensor_slick_concordance"
        assert assessment.concordance_level == ConcordanceLevel.MULTI_SENSOR_CONCORDANCE
        glint_ev = [
            e
            for e in assessment.evidence_items
            if e.modality == ModalityType.OPTICAL_SENTINEL_2
        ]
        assert len(glint_ev) == 1
        assert glint_ev[0].consistency == EvidenceConsistency.SUPPORTING


class TestRegistryIntegration:
    def test_registry_get_wind_aware_screener(self) -> None:
        from app.vision.registry import get_wind_aware_screener, reset_detectors
        reset_detectors()
        screener = get_wind_aware_screener()
        assert isinstance(screener, WindAwareSARScreener)
        assert screener.detector.name == "sar-dark-formation"
