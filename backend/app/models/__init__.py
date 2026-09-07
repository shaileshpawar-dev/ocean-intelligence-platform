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
    Severity,
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

__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "Base",
    "DetectionMethod",
    "DriftReport",
    "DriftStatus",
    "EvidenceLevel",
    "ModelStatus",
    "ModelVersion",
    "PollutionEvent",
    "PollutionSignature",
    "PredictionLog",
    "Region",
    "Report",
    "ResearchChunk",
    "ResearchDocument",
    "RiskAssessment",
    "SatelliteObservation",
    "Severity",
    "TimestampMixin",
    "ZoneHistory",
    "utcnow",
]
