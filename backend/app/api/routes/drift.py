"""FastAPI router for Lagrangian oil-spill drift trajectory simulations (Phase 16)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.drift import DriftSimulationOut, DriftSimulationRequestIn
from app.services import drift_service

router = APIRouter(prefix="/drift", tags=["drift"])


@router.post("/simulate", response_model=DriftSimulationOut)
def run_drift_simulation(
    payload: DriftSimulationRequestIn,
    db: Session = Depends(get_db),
) -> DriftSimulationOut:
    """Execute numerical Lagrangian particle drift & weathering simulation."""
    return drift_service.run_drift_simulation(db=db, payload=payload)


@router.get("/simulations/{simulation_id}", response_model=DriftSimulationOut)
def get_simulation(
    simulation_id: str,
    db: Session = Depends(get_db),
) -> DriftSimulationOut:
    """Retrieve full results of an existing drift simulation."""
    res = drift_service.get_drift_simulation(db=db, simulation_id=simulation_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {simulation_id!r} not found.",
        )
    return res
