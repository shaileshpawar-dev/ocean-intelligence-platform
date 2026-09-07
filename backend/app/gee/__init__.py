"""Satellite ingestion package and provider selection."""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.gee.base import ObservationDTO, SatelliteDataProvider
from app.gee.demo_provider import DemoSatelliteProvider
from app.gee.earth_engine import EarthEngineService
from app.gee.regions import REGIONS, GridCell, RegionDefinition, all_cells, build_grid

logger = get_logger(__name__)

_provider: SatelliteDataProvider | None = None


def get_satellite_provider() -> SatelliteDataProvider:
    """Return the active satellite provider.

    Prefers a real Earth Engine session. Falls back to the clearly-labelled
    demo provider when GEE is unconfigured or unreachable, so the platform
    always starts.
    """
    global _provider
    if _provider is not None:
        return _provider

    if settings.gee_configured:
        service = EarthEngineService()
        if service.is_available:
            _provider = service
            return _provider
        logger.warning("gee_unavailable_using_demo_provider")

    if not settings.demo_mode:
        logger.warning(
            "no_satellite_provider",
            extra={
                "detail": (
                    "GEE is unavailable and DEMO_MODE is false. Satellite "
                    "endpoints will report unavailable rather than serve "
                    "synthetic data."
                )
            },
        )
    _provider = DemoSatelliteProvider()
    return _provider


def reset_provider() -> None:
    """Clear the cached provider. Used between tests."""
    global _provider
    _provider = None


__all__ = [
    "REGIONS",
    "DemoSatelliteProvider",
    "EarthEngineService",
    "GridCell",
    "ObservationDTO",
    "RegionDefinition",
    "SatelliteDataProvider",
    "all_cells",
    "build_grid",
    "get_satellite_provider",
    "reset_provider",
]
