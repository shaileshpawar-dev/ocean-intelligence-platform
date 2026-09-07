"""Geographic context: coastline and protected-area proximity.

Both quantities feed the risk engine, and both are *approximations* whose
precision is reported alongside the value. The alternative -- shipping a
number with no stated precision -- is how a 3 dB estimate becomes a
"142 km sq oil spill" in a dashboard.

Production replacement path:
  * coastline  -> GSHHG / OSM coastline polygons via a spatial index
  * protected  -> the full WDPA marine subset (protectedplanet.net)

Both are documented in ``docs/limitations.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class ProximityResult:
    """A distance estimate together with how much to trust it."""

    distance_km: float
    nearest_name: str
    #: Free-text description of how the number was derived and its error scale.
    precision_note: str


@dataclass(frozen=True, slots=True)
class ProtectedArea:
    """A marine protected area, referenced by approximate centroid."""

    name: str
    country: str
    lat: float
    lon: float
    designation: str


#: A curated subset of internationally recognised marine protected areas whose
#: centroids fall near the platform's monitored regions. Coordinates are
#: approximate centroids, not boundaries: a centroid-distance under-states
#: proximity for large reserves such as Papahanaumokuakea. This is a
#: deliberate, documented simplification, NOT a mirror of the WDPA.
PROTECTED_AREAS: tuple[ProtectedArea, ...] = (
    ProtectedArea("Great Barrier Reef Marine Park", "AU", -18.30, 147.70, "Marine Park"),
    ProtectedArea(
        "Papahanaumokuakea Marine National Monument",
        "US",
        25.70,
        -171.70,
        "Marine Monument",
    ),
    ProtectedArea("Galapagos Marine Reserve", "EC", -0.50, -90.50, "Marine Reserve"),
    ProtectedArea("Banc d'Arguin National Park", "MR", 20.20, -16.40, "National Park"),
    ProtectedArea("Wadden Sea", "NL/DE/DK", 53.60, 7.50, "World Heritage Site"),
    ProtectedArea(
        "Gulf of Mannar Marine National Park", "IN", 9.10, 79.20, "Marine National Park"
    ),
    ProtectedArea("Sundarbans", "IN/BD", 21.90, 89.20, "World Heritage Site"),
    ProtectedArea("Ras Mohammed National Park", "EG", 27.80, 34.25, "National Park"),
    ProtectedArea(
        "Tubbataha Reefs Natural Park", "PH", 8.90, 119.90, "World Heritage Site"
    ),
    ProtectedArea("Wakatobi National Park", "ID", -5.40, 123.60, "National Park"),
    ProtectedArea("Pelagos Sanctuary", "FR/IT/MC", 42.50, 8.50, "Cetacean Sanctuary"),
    ProtectedArea(
        "Florida Keys National Marine Sanctuary", "US", 24.70, -81.40, "Marine Sanctuary"
    ),
    ProtectedArea("Flower Garden Banks NMS", "US", 27.90, -93.80, "Marine Sanctuary"),
    ProtectedArea(
        "Marawah Marine Biosphere Reserve", "AE", 24.30, 53.30, "Biosphere Reserve"
    ),
    ProtectedArea("Socotra Archipelago", "YE", 12.50, 53.90, "World Heritage Site"),
    ProtectedArea("Aldabra Atoll", "SC", -9.40, 46.40, "World Heritage Site"),
    ProtectedArea("Bijagos Archipelago", "GW", 11.20, -16.00, "Biosphere Reserve"),
    ProtectedArea("Dongsha Atoll National Park", "TW", 20.70, 116.70, "National Park"),
    ProtectedArea(
        "Yellow Sea Migratory Bird Sanctuaries",
        "CN",
        33.00,
        120.60,
        "World Heritage Site",
    ),
    ProtectedArea(
        "Sian Ka'an Biosphere Reserve", "MX", 19.50, -87.60, "Biosphere Reserve"
    ),
)

#: Coastal reference points used as a coarse coastline proxy. These are real
#: major ports and headlands; distance to the nearest one over-states true
#: coastline distance wherever coverage is sparse. Reported precision note
#: makes that explicit.
COASTAL_REFERENCE_POINTS: tuple[tuple[str, float, float], ...] = (
    ("Mumbai, IN", 18.94, 72.84),
    ("Kochi, IN", 9.97, 76.24),
    ("Chennai, IN", 13.09, 80.29),
    ("Kolkata, IN", 22.54, 88.33),
    ("Karachi, PK", 24.85, 67.01),
    ("Chittagong, BD", 22.33, 91.81),
    ("Colombo, LK", 6.94, 79.84),
    ("Muscat, OM", 23.61, 58.59),
    ("Dubai, AE", 25.27, 55.30),
    ("Doha, QA", 25.29, 51.53),
    ("Kuwait City, KW", 29.37, 47.98),
    ("Bandar Abbas, IR", 27.18, 56.28),
    ("Jeddah, SA", 21.49, 39.19),
    ("Port Sudan, SD", 19.62, 37.22),
    ("Suez, EG", 29.97, 32.55),
    ("Aden, YE", 12.79, 45.04),
    ("Djibouti, DJ", 11.59, 43.15),
    ("Mombasa, KE", -4.04, 39.67),
    ("Dar es Salaam, TZ", -6.79, 39.28),
    ("Maputo, MZ", -25.97, 32.57),
    ("Cape Town, ZA", -33.92, 18.42),
    ("Lagos, NG", 6.45, 3.39),
    ("Port Harcourt, NG", 4.82, 7.05),
    ("Abidjan, CI", 5.32, -4.03),
    ("Accra, GH", 5.56, -0.19),
    ("Dakar, SN", 14.69, -17.45),
    ("Casablanca, MA", 33.57, -7.59),
    ("Algiers, DZ", 36.75, 3.06),
    ("Tunis, TN", 36.81, 10.18),
    ("Tripoli, LY", 32.89, 13.19),
    ("Alexandria, EG", 31.20, 29.92),
    ("Athens, GR", 37.94, 23.65),
    ("Naples, IT", 40.84, 14.25),
    ("Marseille, FR", 43.30, 5.37),
    ("Barcelona, ES", 41.38, 2.19),
    ("Valencia, ES", 39.45, -0.33),
    ("Lisbon, PT", 38.71, -9.14),
    ("Rotterdam, NL", 51.92, 4.48),
    ("Hamburg, DE", 53.55, 9.99),
    ("Aberdeen, GB", 57.15, -2.09),
    ("Bergen, NO", 60.39, 5.32),
    ("Gdansk, PL", 54.35, 18.65),
    ("Singapore, SG", 1.29, 103.85),
    ("Port Klang, MY", 3.00, 101.39),
    ("Jakarta, ID", -6.11, 106.87),
    ("Surabaya, ID", -7.21, 112.73),
    ("Manila, PH", 14.58, 120.98),
    ("Ho Chi Minh City, VN", 10.77, 106.70),
    ("Bangkok, TH", 13.44, 100.60),
    ("Hong Kong, HK", 22.29, 114.16),
    ("Shanghai, CN", 31.23, 121.47),
    ("Qingdao, CN", 36.07, 120.38),
    ("Tianjin, CN", 38.98, 117.70),
    ("Busan, KR", 35.10, 129.04),
    ("Incheon, KR", 37.46, 126.63),
    ("Tokyo, JP", 35.65, 139.84),
    ("Houston, US", 29.76, -95.36),
    ("New Orleans, US", 29.95, -90.07),
    ("Tampa, US", 27.95, -82.46),
    ("Veracruz, MX", 19.17, -96.13),
    ("Havana, CU", 23.13, -82.38),
    ("Miami, US", 25.77, -80.19),
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


class GeographicDataProvider:
    """Coarse geographic context lookups.

    Implemented against bundled reference data so the platform has no hard
    dependency on an external GIS service. Swap in a real spatial backend by
    subclassing and overriding these two methods.
    """

    name = "bundled-coarse"

    def distance_to_coast(self, lat: float, lon: float) -> ProximityResult:
        """Approximate distance from a point to the nearest coastline."""
        name, dist = min(
            (
                (ref_name, haversine_km(lat, lon, ref_lat, ref_lon))
                for ref_name, ref_lat, ref_lon in COASTAL_REFERENCE_POINTS
            ),
            key=lambda item: item[1],
        )
        return ProximityResult(
            distance_km=round(dist, 1),
            nearest_name=name,
            precision_note=(
                "Approximated as the distance to the nearest of "
                f"{len(COASTAL_REFERENCE_POINTS)} major coastal reference "
                "points, not to the true coastline. Over-states distance "
                "where reference coverage is sparse; typical error is tens "
                "to low hundreds of km."
            ),
        )

    def nearest_protected_area(self, lat: float, lon: float) -> ProximityResult:
        """Approximate distance to the nearest marine protected area centroid."""
        area, dist = min(
            (
                (area, haversine_km(lat, lon, area.lat, area.lon))
                for area in PROTECTED_AREAS
            ),
            key=lambda item: item[1],
        )
        return ProximityResult(
            distance_km=round(dist, 1),
            nearest_name=f"{area.name} ({area.designation}, {area.country})",
            precision_note=(
                f"Distance to the approximate centroid of one of "
                f"{len(PROTECTED_AREAS)} curated marine protected areas. "
                "Centroid distance under-states proximity for large reserves. "
                "Not a WDPA mirror; absence here does not mean absence of "
                "protection."
            ),
        )


_provider: GeographicDataProvider | None = None


def get_geographic_provider() -> GeographicDataProvider:
    """Return the process-wide geographic provider."""
    global _provider
    if _provider is None:
        _provider = GeographicDataProvider()
    return _provider
