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
from app.models.drift_simulation import DriftSimulation
from app.models.environmental_impact import (
    CandidateEnvironmentalImpact,
    MarineReceptor,
)
from app.models.vessel import (
    CandidateVesselAssociation,
    Vessel,
    VesselPosition,
)
from app.models.sar_candidate import (
    SARCandidate,
    SARCandidateOpticalEvidence,
    SARCandidateReview,
)
from app.models.water import (
    DataSource,
    District,
    IngestionRun,
    MonitoringStation,
    RiverStretch,
    SourceResourceState,
    State,
    WaterBody,
    WaterBodyStatusHistory,
    WaterEvidence,
    WaterQualityObservation,
)
from app.models.water_geo import (
    AdminBoundary,
    City,
    ReferenceStandard,
    ReferenceThreshold,
    SourceClassification,
    WaterBodyGeometry,
    WaterImage,
)

__all__ = [
    "AdminBoundary",
    "AgentRun",
    "AgentRunStatus",
    "Base",
    "City",
    "DataSource",
    "DetectionMethod",
    "District",
    "DriftReport",
    "CandidateEnvironmentalImpact",
    "DriftSimulation",
    "MarineReceptor",
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
    "ReferenceStandard",
    "ReferenceThreshold",
    "Region",
    "Report",
    "ResearchChunk",
    "ResearchDocument",
    "RiskAssessment",
    "RiverStretch",
    "SARCandidate",
    "CandidateVesselAssociation",
    "SARCandidateOpticalEvidence",
    "SARCandidateReview",
    "Vessel",
    "VesselPosition",
    "SatelliteObservation",
    "Severity",
    "SourceClassification",
    "SourceResourceState",
    "State",
    "TimestampMixin",
    "WaterBody",
    "WaterBodyGeometry",
    "WaterBodyStatusHistory",
    "WaterBodyType",
    "WaterEvidence",
    "WaterEvidenceType",
    "WaterImage",
    "WaterQualityObservation",
    "WaterStatus",
    "ZoneHistory",
    "utcnow",
]
