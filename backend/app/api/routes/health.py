"""Health, liveness and readiness endpoints.

Three questions, three answers, because a load balancer and an orchestrator
ask different things:

``/health/live``
    Is this process alive? No dependency is touched, so a database outage
    never causes the container to be killed and restarted pointlessly.

``/health/ready``
    Can this process serve? The database is queried. **503** when it cannot,
    so an ALB target group takes the task out of rotation instead of sending
    traffic to a container that can only return errors.

``/health``
    The full picture for a human or a dashboard: every component, with the
    detail. It returns **503** when the database is unusable -- a service
    that cannot read its own data is not healthy, whatever it says in the
    body -- and 200 when only optional components are missing, because an
    absent Earth Engine session degrades the platform rather than breaking
    it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.gee import get_satellite_provider
from app.schemas.common import HealthComponent, HealthResponse
from app.vision.registry import get_image_detector, get_sar_detector

router = APIRouter(tags=["system"])


@router.get("/health/live", summary="Liveness: is the process alive?")
def liveness() -> dict:
    """Answer without touching any dependency.

    This is what the container health check and the orchestrator use. A
    database outage must not make every task look dead and trigger a restart
    loop that cannot possibly fix it.
    """
    return {
        "status": "alive",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("/health/ready", summary="Readiness: can this task serve traffic?")
def readiness(response: Response, db: Session = Depends(get_db)) -> dict:
    """Query the database, and say no if it cannot be reached.

    Returns 503 when the database is unavailable so a load balancer stops
    sending traffic here. The spatial backend is reported but does not gate
    readiness: without PostGIS the application still serves, using the Python
    fallback paths.
    """
    from app.core.dbinfo import backend_info

    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        response.status_code = 503
        return {
            "status": "not_ready",
            "reason": "database_unavailable",
            "detail": type(exc).__name__,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    info = backend_info()
    return {
        "status": "ready",
        "database": info.label,
        "spatial_sql": info.spatial_ready,
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    """Report the status of every component.

    200 when the database is usable, whatever else is missing: an absent
    Earth Engine session degrades the platform, it does not break it. **503**
    when the database is unusable, because the platform is a database with a
    web interface and cannot answer a single question without it.
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
    if degraded:
        # Not an opinion in the body: the status code says it too.
        response.status_code = 503
    return HealthResponse(
        status="unhealthy" if degraded else "ok",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        components=components,
        checked_at=datetime.now(UTC),
    )
