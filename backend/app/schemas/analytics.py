"""Schemas for trends, forecasts and model metadata."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TrendPointOut(BaseModel):
    """One day in a region's activity series."""

    date: str
    event_count: int
    mean_risk: float | None = None
    max_risk: float | None = None
    mean_confidence: float | None = None
    total_area_km2: float | None = None
    mean_backscatter_db: float | None = None
    evidence_level: str


class RegionTrendOut(BaseModel):
    """A region's series plus how much of the window was actually observed."""

    region_code: str
    region_name: str
    parent_region: str | None = None
    series: list[TrendPointOut]
    latest_risk: float | None = None
    change: float | None = None
    slope_per_day: float | None = None
    coverage_days: int
    window_days: int
    coverage_ratio: float = Field(
        description=(
            "Observed days divided by window length. A low ratio means gaps, "
            "not calm: satellite revisit intervals leave regions unobserved."
        )
    )
    contains_simulated_data: bool = False


class ForecastPointOut(BaseModel):
    """One forecast step with its prediction interval."""

    target_date: str
    horizon_days: int
    value: float
    lower: float
    upper: float
    interval_confidence: float


class ForecastBandOut(BaseModel):
    """A forecast step expressed as a severity band."""

    date: str
    horizon_days: int
    risk: float
    severity: str
    lower: float
    upper: float
    severity_lower: str
    severity_upper: str
    interval_confidence: float


class ForecastOut(BaseModel):
    """A forecast plus the evidence that it is worth anything."""

    region_code: str
    #: Which measured Sentinel-2 index was projected, when one was. None
    #: means this is the detection-activity forecast.
    index: str | None = None
    model_name: str
    forecast_kind: str = Field(
        description=(
            "'detection_activity' -- the trend in this platform's own "
            "detections. Never physical pollutant dispersion."
        )
    )
    status: str
    points: list[ForecastPointOut] = Field(default_factory=list)
    bands: list[ForecastBandOut] = Field(default_factory=list)
    n_observations: int
    backtest_mae: float | None = None
    naive_mae: float | None = None
    beats_naive: bool | None = Field(
        default=None,
        description=(
            "Whether the model beat last-value-carried-forward in backtesting. "
            "False means the forecast adds no information over the baseline."
        ),
    )
    message: str = ""
    caveats: list[str] = Field(default_factory=list)


class ModelVersionOut(BaseModel):
    """A registered model and its measured metrics.

    Null metrics mean "not evaluated". They are never filled with a
    placeholder, because a fabricated mAP is worse than an absent one.
    """

    name: str
    version: str
    task: str
    framework: str | None = None
    status: str
    is_deployed: bool
    dataset_version: str | None = None
    trained_at: str | None = None

    map50: float | None = None
    map50_95: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    iou: float | None = None
    mean_latency_ms: float | None = None

    class_names: list[str] | None = None
    metrics_source: str | None = None
    notes: str | None = None


class DetectorInfoOut(BaseModel):
    """Runtime status of a loaded detector."""

    name: str
    version: str
    method: str
    available: bool
    #: The one detector whose output the platform presents. Asking
    #: for "the first available detector" returned the mock.
    is_active: bool = False
    #: True for the demonstration stub: it runs, and measures nothing.
    is_simulated: bool = False
    supported_signatures: list[str] = Field(
        description=(
            "Signatures this detector is permitted to emit. Emitting anything "
            "outside this set raises, which is what stops a SAR detector "
            "claiming an optical-only class."
        )
    )
    class_names: dict[int, str] | None = Field(
        default=None,
        description=(
            "Trained labels read from the checkpoint itself, not from a "
            "hardcoded table. Present only for learned detectors."
        ),
    )
    checkpoint: str | None = Field(
        default=None, description="Path to the loaded weights, when applicable."
    )

    # Everything below is reported by the evaluated SAR screeners and was
    # previously dropped on the floor: the detector's describe() carried its
    # own measured metrics, and this schema kept only seven fields, so the API
    # said nothing about models that had in fact been evaluated. All optional,
    # because the mock and rule-based detectors do not have any of it.
    architecture: str | None = Field(
        default=None, description="Network architecture, for learned detectors."
    )
    modality: str | None = Field(
        default=None, description="Sensor and product the detector expects."
    )
    input_resolution: list[int] | None = Field(
        default=None, description="Input size in pixels, as [height, width]."
    )
    evaluation_status: str | None = Field(
        default=None,
        description=(
            "How far this detector has been validated. "
            "'evaluated_on_labeled_test_data' means a held-out split was "
            "scored; it does not mean validated in operation."
        ),
    )
    dataset_provenance: str | None = Field(
        default=None, description="Source and licence of the evaluation data."
    )
    is_default: bool | None = Field(
        default=None, description="Whether this detector is the operational baseline."
    )
    role: str | None = Field(
        default=None, description="What this detector is for, relative to the baseline."
    )
    test_metrics: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Measured results on the detector's own held-out test split, as "
            "recorded at evaluation time. Null means not evaluated, never zero."
        ),
    )
    baseline_comparison: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The same test split scored by earlier models and by the "
            "rule-based baseline, so a reader can see what the model beat."
        ),
    )
