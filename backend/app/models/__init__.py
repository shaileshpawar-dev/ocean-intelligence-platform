"""SQLAlchemy ORM models.

Importing this package registers every table on :data:`Base.metadata`, which
is what :func:`app.core.database.init_db` relies on.
"""

from app.models.base import Base, TimestampMixin, utcnow
from app.models.enums import (
    AgentRunStatus,
    DetectionMethod,
    DriftStatus,
    EvidenceLevel,
    ModelStatus,
    PollutionSignature,
    QualityFlag,
    Severity,
    WaterBodyType,
    WaterEvidenceType,
    WaterStatus,
)
from app.models.intelligence import (
    AgentRun,
    Report,
    ResearchChunk,
    ResearchDocument,
)
from app.models.ml import DriftReport, ModelVersion, PredictionLog
from app.models.pollution import (
    PollutionEvent,
    Region,
    RiskAssessment,
    SatelliteObservation,
    ZoneHistory,
)
from app.models.water import (
    DataSource,
    District,
    IngestionRun,
    MonitoringStation,
    RiverStretch,
    State,
    WaterBody,
    WaterBodyStatusHistory,
    WaterEvidence,
    WaterQualityObservation,
)

__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "Base",
    "DataSource",
    "DetectionMethod",
    "District",
    "DriftReport",
    "DriftStatus",
    "EvidenceLevel",
    "IngestionRun",
    "ModelStatus",
    "ModelVersion",
    "MonitoringStation",
    "PollutionEvent",
    "PollutionSignature",
    "PredictionLog",
    "QualityFlag",
    "Region",
    "Report",
    "ResearchChunk",
    "ResearchDocument",
    "RiskAssessment",
    "RiverStretch",
    "SatelliteObservation",
    "Severity",
    "State",
    "TimestampMixin",
    "WaterBody",
    "WaterBodyStatusHistory",
    "WaterBodyType",
    "WaterEvidence",
    "WaterEvidenceType",
    "WaterQualityObservation",
    "WaterStatus",
    "ZoneHistory",
    "utcnow",
]
