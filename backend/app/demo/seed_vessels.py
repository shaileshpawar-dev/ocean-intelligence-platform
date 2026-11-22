"""Seed realistic commercial vessel registry and AIS ping trajectories (Phase 15)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.sar_candidate import SARCandidate
from app.models.vessel import CandidateVesselAssociation, Vessel, VesselPosition
from app.vision.ais_associator import AISAssociationEngine

logger = get_logger(__name__)

SEED_VESSELS = [
    {
        "mmsi": "240123000",
        "imo": "9481234",
        "name": "MT Starlight",
        "callsign": "SVAB2",
        "vessel_type": "Crude Oil Tanker",
        "flag_country": "Liberia",
        "length_m": 274.0,
        "width_m": 48.0,
        "draught_m": 16.5,
        "risk_profile": "STANDARD",
    },
    {
        "mmsi": "636015000",
        "imo": "9512345",
        "name": "Chem Polaris",
        "callsign": "A8TX5",
        "vessel_type": "Chemical Tanker",
        "flag_country": "Panama",
        "length_m": 182.0,
        "width_m": 32.0,
        "draught_m": 11.2,
        "risk_profile": "HIGH_RISK_FLAG",
    },
    {
        "mmsi": "352001000",
        "imo": "9324567",
        "name": "Pacific Voyager",
        "callsign": "3FAA8",
        "vessel_type": "Container Ship",
        "flag_country": "Marshall Islands",
        "length_m": 366.0,
        "width_m": 51.0,
        "draught_m": 14.8,
        "risk_profile": "STANDARD",
    },
    {
        "mmsi": "255805000",
        "imo": "9215678",
        "name": "MSC Sandra",
        "callsign": "CQAB",
        "vessel_type": "Container Ship",
        "flag_country": "Cyprus",
        "length_m": 294.0,
        "width_m": 40.0,
        "draught_m": 13.0,
        "risk_profile": "STANDARD",
    },
    {
        "mmsi": "419001234",
        "imo": "9678901",
        "name": "Sea Pioneer",
        "callsign": "AWSD",
        "vessel_type": "Bulk Carrier",
        "flag_country": "India",
        "length_m": 225.0,
        "width_m": 32.2,
        "draught_m": 14.1,
        "risk_profile": "STANDARD",
    },
    {
        "mmsi": "563002345",
        "imo": "9789012",
        "name": "Ocean Pride",
        "callsign": "9V6789",
        "vessel_type": "Oil Products Tanker",
        "flag_country": "Singapore",
        "length_m": 183.0,
        "width_m": 32.0,
        "draught_m": 11.8,
        "risk_profile": "STANDARD",
    },
]


def seed_vessels_and_tracks(db: Session) -> None:
    """Seed commercial vessels and generate trajectory pings collocated with candidate observations."""
    # 1. Seed vessels
    for vdata in SEED_VESSELS:
        existing = db.query(Vessel).filter_by(mmsi=vdata["mmsi"]).first()
        if not existing:
            vessel = Vessel(**vdata)
            db.add(vessel)
    db.commit()

    # 2. Query target candidates to align tracks
    c_s1_36 = db.query(SARCandidate).filter_by(candidate_id="cand_s1_0036").first()
    c_std_1 = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()

    positions_to_add: list[VesselPosition] = []

    # Track 1: MT Starlight near cand_s1_0036 (Mediterranean)
    if c_s1_36:
        base_t = c_s1_36.acquisition_timestamp
        base_lat = c_s1_36.latitude
        base_lon = c_s1_36.longitude

        # Generate 7 pings (-3h to +3h) along heading ~085 deg
        for h in range(-3, 4):
            t = base_t + timedelta(hours=h)
            # ~12 knots = ~22 km/h -> ~0.2 deg lon per hour
            lat = base_lat + (h * 0.015) + 0.035  # CPA ~4 km north
            lon = base_lon + (h * 0.20)
            existing_pos = (
                db.query(VesselPosition)
                .filter_by(mmsi="240123000", timestamp=t)
                .first()
            )
            if not existing_pos:
                positions_to_add.append(
                    VesselPosition(
                        mmsi="240123000",
                        timestamp=t,
                        latitude=round(lat, 5),
                        longitude=round(lon, 5),
                        speed_knots=12.4,
                        heading_deg=85.0,
                        nav_status="Under way using engine",
                        destination="PORT SAID",
                    )
                )

        # Distant vessel: MSC Sandra passing 35 km away
        for h in range(-3, 4):
            t = base_t + timedelta(hours=h)
            lat = base_lat - 0.32 + (h * 0.01)
            lon = base_lon + (h * 0.22)
            existing_pos = (
                db.query(VesselPosition)
                .filter_by(mmsi="255805000", timestamp=t)
                .first()
            )
            if not existing_pos:
                positions_to_add.append(
                    VesselPosition(
                        mmsi="255805000",
                        timestamp=t,
                        latitude=round(lat, 5),
                        longitude=round(lon, 5),
                        speed_knots=16.8,
                        heading_deg=88.0,
                        nav_status="Under way using engine",
                        destination="PIRAEUS",
                    )
                )

    # Track 2: Chem Polaris near cand_test_standard_001 (Arabian Sea)
    if c_std_1:
        base_t = c_std_1.acquisition_timestamp
        base_lat = c_std_1.latitude
        base_lon = c_std_1.longitude

        # Chem Polaris transiting close (~6 km CPA)
        for h in range(-3, 4):
            t = base_t + timedelta(hours=h)
            lat = base_lat + (h * 0.18)
            lon = base_lon + (h * 0.02) + 0.05
            existing_pos = (
                db.query(VesselPosition)
                .filter_by(mmsi="636015000", timestamp=t)
                .first()
            )
            if not existing_pos:
                positions_to_add.append(
                    VesselPosition(
                        mmsi="636015000",
                        timestamp=t,
                        latitude=round(lat, 5),
                        longitude=round(lon, 5),
                        speed_knots=11.2,
                        heading_deg=175.0,
                        nav_status="Under way using engine",
                        destination="MUMBAI",
                    )
                )

        # Sea Pioneer transiting in vicinity (~22 km CPA)
        for h in range(-3, 4):
            t = base_t + timedelta(hours=h)
            lat = base_lat + (h * 0.15) - 0.20
            lon = base_lon + (h * 0.04)
            existing_pos = (
                db.query(VesselPosition)
                .filter_by(mmsi="419001234", timestamp=t)
                .first()
            )
            if not existing_pos:
                positions_to_add.append(
                    VesselPosition(
                        mmsi="419001234",
                        timestamp=t,
                        latitude=round(lat, 5),
                        longitude=round(lon, 5),
                        speed_knots=13.0,
                        heading_deg=170.0,
                        nav_status="Under way using engine",
                        destination="KANDLA",
                    )
                )

    if positions_to_add:
        db.add_all(positions_to_add)
        db.commit()

    # 3. Trigger correlation for target candidates
    engine = AISAssociationEngine()
    if c_s1_36:
        engine.correlate_candidate(db, "cand_s1_0036")
    if c_std_1:
        engine.correlate_candidate(db, "cand_test_standard_001")

    logger.info("Successfully seeded vessels and ran AIS candidate correlations.")
