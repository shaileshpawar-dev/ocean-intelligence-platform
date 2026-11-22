"""Pydantic schemas for AIS commercial vessels and candidate association (Phase 15)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class VesselPositionOut(BaseModel):
    """A timestamped AIS broadcast ping along a vessel trajectory."""

    id: int
    mmsi: str
    timestamp: datetime
    latitude: float
    longitude: float
    speed_knots: float
    heading_deg: float
    nav_status: str
    destination: str | None = None

    model_config = {"from_attributes": True}


class VesselOut(BaseModel):
    """Particulars and risk profile for a commercial vessel."""

    mmsi: str
    imo: str | None = None
    name: str
    callsign: str | None = None
    vessel_type: str
    flag_country: str
    length_m: float | None = None
    width_m: float | None = None
    draught_m: float | None = None
    risk_profile: str

    model_config = {"from_attributes": True}


class VesselDetailOut(VesselOut):
    """Detailed vessel particulars with full trajectory ping history."""

    positions: list[VesselPositionOut] = Field(default_factory=list)


class CandidateVesselAssociationOut(BaseModel):
    """Spatio-temporal correlation between a candidate surface slick and an AIS track."""

    id: int
    candidate_id: str
    mmsi: str
    vessel_name: str
    vessel_type: str
    flag_country: str
    association_type: str
    spatial_distance_km: float
    temporal_offset_minutes: float
    interpolated_lat: float
    interpolated_lon: float
    association_score: float
    is_primary_suspect: bool
    notes: str | None = None

    model_config = {"from_attributes": True}
