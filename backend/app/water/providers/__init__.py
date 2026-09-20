"""Water-data source adapters.

Only providers that read a genuinely accessible source are registered. A
source the platform cannot actually reach is described in
docs/DATA_SOURCES.md as unimplemented rather than being given a stub adapter
that would look like an integration in the UI.
"""

from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderError,
    ProviderInfo,
    ProviderUnavailableError,
    WaterDataProvider,
)
from app.water.providers.nwdp_cpcb import NWDPCPCBProvider

PROVIDERS: dict[str, type[WaterDataProvider]] = {
    "cpcb_nwdp": NWDPCPCBProvider,
}


def get_provider(key: str) -> WaterDataProvider:
    """Instantiate a registered provider by key."""
    try:
        return PROVIDERS[key]()
    except KeyError as exc:
        raise KeyError(
            f"Unknown provider '{key}'. Registered: {sorted(PROVIDERS)}"
        ) from exc


def all_providers() -> list[WaterDataProvider]:
    """Every registered provider, instantiated."""
    return [cls() for cls in PROVIDERS.values()]


__all__ = [
    "PROVIDERS",
    "FetchPlan",
    "NWDPCPCBProvider",
    "ObservationRow",
    "ProviderError",
    "ProviderInfo",
    "ProviderUnavailableError",
    "WaterDataProvider",
    "all_providers",
    "get_provider",
]
