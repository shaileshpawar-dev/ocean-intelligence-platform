"""FastAPI router for marine protected areas and environmental impact (Phase 17)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.environmental_impact import MarineReceptorOut
from app.services import environmental_impact_service

router = APIRouter(prefix="/receptors", tags=["receptors"])


@router.get("", response_model=list[MarineReceptorOut])
def list_marine_receptors(
    category: str | None = Query(default=None, description="Filter by receptor category"),
    search: str | None = Query(default=None, description="Search receptor by name or jurisdiction"),
    db: Session = Depends(get_db),
) -> list[MarineReceptorOut]:
    """List Marine Protected Areas, coral reef sanctuaries, mangroves, and critical coastal intakes."""
    return environmental_impact_service.list_marine_receptors(
        db=db,
        category=category,
        search=search,
    )
