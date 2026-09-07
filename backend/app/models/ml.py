"""ML lifecycle tables: model registry, prediction logs and drift reports."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import DriftStatus, ModelStatus


class ModelVersion(Base, TimestampMixin):
    """A registered model version and its evaluated metrics.

    Metrics are nullable on purpose. A registered model with no metrics is an
    honest statement that it has not been evaluated yet -- the API reports it
    as ``null`` rather than inventing an mAP.
    """

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(String(64))  # detection | segmentation | forecast
    framework: Mapped[str | None] = mapped_column(String(64))

    dataset_version: Mapped[str | None] = mapped_column(String(64))
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_uri: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(32), default=ModelStatus.DEVELOPMENT, index=True
    )
    is_deployed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Evaluated metrics. Null means "not measured", never zero.
    map50: Mapped[float | None] = mapped_column(Float)
    map50_95: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)
    f1: Mapped[float | None] = mapped_column(Float)
    iou: Mapped[float | None] = mapped_column(Float)
    mean_latency_ms: Mapped[float | None] = mapped_column(Float)

    hyperparameters: Mapped[dict | None] = mapped_column(JSON)
    class_names: Mapped[list | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    metrics_source: Mapped[str | None] = mapped_column(String(128))


class PredictionLog(Base):
    """One row per inference call. Feeds latency stats and drift detection."""

    __tablename__ = "prediction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    model_name: Mapped[str] = mapped_column(String(128), index=True)
    model_version: Mapped[str] = mapped_column(String(64), index=True)
    endpoint: Mapped[str] = mapped_column(String(128))

    latency_ms: Mapped[float] = mapped_column(Float)
    detection_count: Mapped[int] = mapped_column(Integer, default=0)
    max_confidence: Mapped[float | None] = mapped_column(Float)
    mean_confidence: Mapped[float | None] = mapped_column(Float)
    predicted_classes: Mapped[list | None] = mapped_column(JSON)

    # Coarse input statistics used for drift monitoring without retaining
    # the image itself.
    input_stats: Mapped[dict | None] = mapped_column(JSON)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


class DriftReport(Base, TimestampMixin):
    """Result of comparing a recent window of predictions to a baseline."""

    __tablename__ = "drift_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    metric: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=DriftStatus.OK, index=True)

    baseline_window_days: Mapped[int] = mapped_column(Integer)
    current_window_days: Mapped[int] = mapped_column(Integer)
    baseline_n: Mapped[int] = mapped_column(Integer)
    current_n: Mapped[int] = mapped_column(Integer)

    statistic: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict | None] = mapped_column(JSON)
