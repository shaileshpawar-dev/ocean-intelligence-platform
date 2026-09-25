"""Health and readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.gee import get_satellite_provider
from app.schemas.common import HealthComponent, HealthResponse
from app.vision.registry import get_image_detector, get_sar_detector

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """Report liveness and the status of every optional dependency.

    Returns 200 even when optional components are unavailable: an absent
    Earth Engine session degrades the platform, it does not break it. The
    per-component flags say exactly what is and is not working.
    """
    components: list[HealthComponent] = []

    try:
        db.execute(text("SELECT 1"))
        from app.core.dbinfo import backend_info

        components.append(
            HealthComponent(name="database", available=True, detail=backend_info().label)
        )
    except Exception as exc:
        components.append(
            HealthComponent(
                name="database", available=False, detail=f"{type(exc).__name__}"
            )
        )

    provider = get_satellite_provider()
    components.append(
        HealthComponent(
            name=f"satellite:{provider.name}",
            available=provider.is_available,
            detail=(
                "Synthetic provider; outputs are SIMULATED."
                if provider.name == "demo-synthetic"
                else None
            ),
        )
    )

    detector = get_image_detector()
    components.append(
        HealthComponent(
            name=f"detector:{detector.name}",
            available=detector.is_available,
            detail=(
                "Mock detector; outputs are SIMULATED."
                if detector.name == "mock-detector"
                else None
            ),
        )
    )

    sar = get_sar_detector()
    components.append(HealthComponent(name=f"detector:{sar.name}", available=True))

    components.append(
        HealthComponent(
            name=f"llm:{settings.llm_provider}",
            available=settings.llm_provider != "none",
            detail="Set LLM_PROVIDER and the matching API key to enable."
            if settings.llm_provider == "none"
            else None,
        )
    )

    degraded = any(not c.available for c in components if c.name.startswith("database"))
    return HealthResponse(
        status="unhealthy" if degraded else "ok",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        components=components,
        checked_at=datetime.now(UTC),
    )
