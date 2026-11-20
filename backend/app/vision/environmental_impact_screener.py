"""Environmental Impact Screener and Marine Vulnerability Index Engine (Phase 17).

Evaluates marine candidate coordinates and trajectory drift against Marine Protected
Areas (MPAs), sensitive coral reefs, mangrove biospheres, and critical coastal
infrastructure intakes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.environmental_impact import (
    CandidateEnvironmentalImpact,
    MarineReceptor,
)
from app.models.sar_candidate import SARCandidate
from app.vision.ais_associator import haversine_distance_km

logger = get_logger(__name__)


# Default reference receptors for Indian EEZ and benchmark Mediterranean basins
DEFAULT_MARINE_RECEPTORS = [
    {
        "receptor_id": "rec_coral_mannar_01",
        "name": "Gulf of Mannar Marine Biosphere Reserve",
        "category": "CORAL_REEF",
        "jurisdiction": "Tamil Nadu / Indian EEZ",
        "latitude": 9.15,
        "longitude": 79.10,
        "vulnerability_weight": 1.0,
        "description": "High-biodiversity coral reef system, dugong habitat, and seagrass beds.",
    },
    {
        "receptor_id": "rec_mangrove_sundarbans_01",
        "name": "Sundarbans UNESCO Mangrove Biosphere Reserve",
        "category": "MANGROVE_ECOSYSTEM",
        "jurisdiction": "West Bengal / Indian EEZ",
        "latitude": 21.80,
        "longitude": 88.90,
        "vulnerability_weight": 0.95,
        "description": "World's largest contiguous tidal halophytic mangrove ecosystem.",
    },
    {
        "receptor_id": "rec_coral_kachchh_01",
        "name": "Marine National Park (Gulf of Kachchh)",
        "category": "CORAL_REEF",
        "jurisdiction": "Gujarat / Indian EEZ",
        "latitude": 22.45,
        "longitude": 69.40,
        "vulnerability_weight": 0.95,
        "description": "Intertidal live coral reefs, mangrove forests, and fragile marine fauna.",
    },
    {
        "receptor_id": "rec_sanctuary_malvan_01",
        "name": "Malvan Marine Sanctuary",
        "category": "MARINE_PROTECTED_AREA",
        "jurisdiction": "Maharashtra / Indian EEZ",
        "latitude": 16.05,
        "longitude": 73.45,
        "vulnerability_weight": 0.90,
        "description": "Subtidal rocky reefs, pearl oyster beds, and marine turtle foraging grounds.",
    },
    {
        "receptor_id": "rec_desal_nemmeli_01",
        "name": "Nemmeli Coastal Desalination Intake",
        "category": "DESALINATION_INTAKE",
        "jurisdiction": "Chennai Coastal Zone / Tamil Nadu",
        "latitude": 12.72,
        "longitude": 80.24,
        "vulnerability_weight": 0.85,
        "description": "Critical municipal potable seawater intake facility (100 MLD).",
    },
    {
        "receptor_id": "rec_mpa_akamas_01",
        "name": "Akamas Peninsula Marine Protected Area",
        "category": "MARINE_PROTECTED_AREA",
        "jurisdiction": "Cyprus Coastal Waters",
        "latitude": 35.05,
        "longitude": 32.30,
        "vulnerability_weight": 0.90,
        "description": "Pristine Mediterranean marine coastal reserve and green turtle nesting area.",
    },
    {
        "receptor_id": "rec_mpa_greco_01",
        "name": "Cape Greco Marine Protected Area",
        "category": "CORAL_REEF",
        "jurisdiction": "Cyprus Coastal Waters",
        "latitude": 34.96,
        "longitude": 34.08,
        "vulnerability_weight": 0.85,
        "description": "Sea caves, endemic Posidonia oceanica seagrass meadows, and marine reefs.",
    },
    {
        "receptor_id": "rec_harbor_karachi_01",
        "name": "Port Qasim & Korangi Creek Mangroves",
        "category": "MANGROVE_ECOSYSTEM",
        "jurisdiction": "Northern Arabian Sea / Sindh Coastal Zone",
        "latitude": 24.75,
        "longitude": 67.20,
        "vulnerability_weight": 0.90,
        "description": "Critical tidal mangrove creeks, mudflats, and port approach navigable channel.",
    },
    {
        "receptor_id": "rec_mangrove_indus_01",
        "name": "Indus Delta Mangroves & Marine Reserve",
        "category": "MANGROVE_ECOSYSTEM",
        "jurisdiction": "Arabian Sea Coastal Border / Gujarat & Sindh",
        "latitude": 24.30,
        "longitude": 67.50,
        "vulnerability_weight": 0.92,
        "description": "Extensive mangrove delta ecoregion, marine turtle breeding, and coastal fishery habitat.",
    },
]


def seed_marine_receptors(db: Session) -> None:
    """Ensure baseline marine protected areas and critical receptors exist in database."""
    for rdata in DEFAULT_MARINE_RECEPTORS:
        existing = db.get(MarineReceptor, rdata["receptor_id"])
        if not existing:
            rec = MarineReceptor(**rdata)
            db.add(rec)
    db.commit()


class EnvironmentalImpactScreener:
    """Evaluates candidate slick proximity and drift trajectories against sensitive marine receptors."""

    SEARCH_RADIUS_KM: float = 150.0

    def evaluate_candidate(
        self,
        db: Session,
        candidate_id: str,
    ) -> list[CandidateEnvironmentalImpact]:
        """Compute spatial exposure, vulnerability scores, and mitigation priorities for a candidate."""
        cand = db.query(SARCandidate).filter_by(candidate_id=candidate_id).first()
        if not cand:
            raise ValueError(f"Candidate {candidate_id} not found.")

        # Ensure receptors are seeded
        seed_marine_receptors(db)

        # Clear existing impacts
        db.query(CandidateEnvironmentalImpact).filter_by(candidate_id=candidate_id).delete()

        receptors = db.query(MarineReceptor).all()
        impacts: list[CandidateEnvironmentalImpact] = []

        cand_lat = cand.latitude
        cand_lon = cand.longitude
        p_oil = cand.raw_confidence

        for r in receptors:
            dist = haversine_distance_km(cand_lat, cand_lon, r.latitude, r.longitude)
            if dist > self.SEARCH_RADIUS_KM:
                continue

            # Compute composite vulnerability score (0 - 100)
            # Decays with distance (characteristic length scale 30 km)
            dist_factor = math.exp(-dist / 30.0)
            conf_multiplier = 1.0 + (0.35 * p_oil)
            raw_vulnerability = r.vulnerability_weight * dist_factor * 100.0 * conf_multiplier
            vuln_score = round(max(5.0, min(99.0, raw_vulnerability)), 1)

            # Estimated arrival time assuming ~1.5 km/h mean drift velocity toward coast
            est_arrival_h = round(dist / 1.5, 1) if dist <= 80.0 else None

            # Categorize impact severity
            if vuln_score >= 65.0 or dist <= 15.0:
                severity = "CRITICAL"
                action = (
                    f"Immediate priority: Deploy protective deflection booms at {r.name}. "
                    f"Alert coastal management authorities within 3 hours. Estimated arrival: {est_arrival_h}h."
                )
            elif vuln_score >= 40.0 or dist <= 35.0:
                severity = "HIGH"
                action = (
                    f"High vigilance: Stage containment equipment proximate to {r.name}. "
                    f"Monitor trajectory drift vector. Proximity: {dist:.1f} km."
                )
            elif vuln_score >= 20.0 or dist <= 65.0:
                severity = "MODERATE"
                action = f"Secondary monitoring: Notify regional response coordinators of potential sheen drift ({dist:.1f} km)."
            else:
                severity = "LOW"
                action = "Low immediate exposure: Re-evaluate if wind shifts toward coastal corridor."

            impact = CandidateEnvironmentalImpact(
                candidate_id=candidate_id,
                receptor_id=r.receptor_id,
                distance_km=round(dist, 1),
                estimated_arrival_hours=est_arrival_h,
                impact_severity=severity,
                vulnerability_score=vuln_score,
                priority_action=action,
            )
            impacts.append(impact)

        impacts.sort(key=lambda x: x.vulnerability_score, reverse=True)
        for imp in impacts:
            db.add(imp)

        db.commit()
        logger.info(
            "Evaluated environmental impact for %s: %s proximate receptors (max vuln: %s)",
            candidate_id,
            len(impacts),
            impacts[0].vulnerability_score if impacts else 0.0,
        )
        return impacts
