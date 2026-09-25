"""Central Water Commission surface-water quality via the same portal.

Why a second source exists
--------------------------
The CPCB extracts on the National Water Data Portal stop in 2021, so every
CPCB-derived status is honestly "no recent data". The **Central Water
Commission** publishes its own manual surface-water monitoring on the same
portal, and its ``2021-2025`` resources carry observations into 2025 --
including the parameters the reference standards actually govern (BOD, COD,
faecal and total coliform) as well as turbidity, conductivity and
temperature.

Verified against the live portal before this adapter was written:

* The three CWC packages are datastore-backed and unauthenticated, exactly
  like the CPCB ones, so the same CKAN paging is reused by subclassing.
* Resource names carry the state and period, e.g.
  ``swq_physical_parameter_manual_cwc_mh_2021_2025.csv`` and the older
  ``swq_manual_physical_parameters_cwc_mh_1961_2020.csv``.
* Unlike CPCB's extracts, the **River, Basin and Tributary columns are
  populated** ("River: Godavari", "Tributary: Pranhita"), so water-body
  identity comes from the source field rather than from parsing a station
  label -- the strongest identity evidence this platform has.
* Units differ from CPCB's in one place that matters: conductivity is
  published in mS/cm here and µS/cm by CPCB. That is handled by the
  parameter registry, not by silently treating the numbers as equal.

This provider does not replace CPCB. Observations from both are stored side
by side with their own source, and the UI shows which agency measured what,
and when.
"""

from __future__ import annotations

from pathlib import Path

from app.water.freshness import Cadence
from app.water.providers.base import ProviderInfo
from app.water.providers.nwdp_cpcb import NWDPCPCBProvider

CATALOGUE_PATH = Path(__file__).parent / "data" / "nwdp_cwc_catalogue.json"

PACKAGES = {
    "physical": (
        "surface-water-quality-manual-physical-parameters-central-water-commission-cwc"
    ),
    "chemical": (
        "surface-water-quality-manual-chemical-parameters-"
        "andhra-pradesh-central-water-commission-cwc"
    ),
    "biological": "surface-water-quality-manual-biological-parameters-cwc",
}


class NWDPCWCProvider(NWDPCPCBProvider):
    """Reads CWC surface-water observations from the NWDP CKAN datastore.

    Everything about the transport (paging, retry, row explosion) is shared
    with :class:`~app.water.providers.nwdp_cpcb.NWDPCPCBProvider`; only the
    catalogue and the self-description differ.
    """

    def __init__(self, *, catalogue_path: Path | None = None) -> None:
        """Create the provider, optionally overriding the bundled catalogue."""
        super().__init__(catalogue_path=catalogue_path or CATALOGUE_PATH)

    @property
    def info(self) -> ProviderInfo:
        """Self-description, including what this source adds over CPCB."""
        return ProviderInfo(
            key="cwc_nwdp",
            name="CWC Surface Water Quality (Manual)",
            organisation="Central Water Commission via National Water Informatics Centre",
            url="https://nwdp.nwic.gov.in/dataset/?organization=cwc",
            dataset="Surface Water Quality (Manual) — physical, chemical and "
            "biological parameters",
            licence="Other (Open)",
            cadence=Cadence.MONTHLY,
            access="public",
            implemented=True,
            source_type="government",
            observation_method="manual_grab_sample",
            reliability_note=(
                "Central Water Commission's own network, published on the same "
                "portal as CPCB's. Rows reach April 2025, so it is the newer "
                "of the two for the stations it covers."
            ),
            notes=[
                "Public CKAN datastore API; no key or registration required.",
                "Carries observations into 2025, where the CPCB extracts stop "
                "in 2021. Both are kept; neither overwrites the other.",
                "River, Basin and Tributary columns are populated, so water "
                "bodies come from the source field rather than a parsed name.",
                "Conductivity is published in mS/cm here and µS/cm by CPCB; "
                "the parameter registry converts rather than comparing raw "
                "numbers.",
            ],
        )
