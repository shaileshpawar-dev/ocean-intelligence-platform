"""Cities as explicit, documented groupings of districts.

No open, national dataset of Indian municipal boundaries exists that the
platform could cite. Monitoring data is keyed to districts, and each major
city corresponds to one or more whole districts (Greater Mumbai is exactly the
Mumbai and Mumbai Suburban districts). So a city here is a named set of
districts, written down once, with a note saying what the set means.

Position and extent come from the geoBoundaries district polygons, never from
guesses. A city whose districts are not in the boundary file is still created
(it can be searched and scoped by CPCB district) but has no position, and says
so. Nothing here is inferred by a model.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.water import District, State
from app.models.water_geo import AdminBoundary, City
from app.water.boundaries import DISTRICT_ALIASES
from app.water.matching import PLACE_ALIASES, normalise_name, slugify


@dataclass(frozen=True, slots=True)
class CityDef:
    """One curated city: a named set of districts."""

    name: str
    state_code: str
    districts: tuple[str, ...]
    """District names as geoBoundaries ADM2 spells them."""

    aliases: tuple[str, ...] = ()
    note: str = ""


_WHOLE = "City and district coincide; the district is used as the city's extent."

CITY_DEFS: tuple[CityDef, ...] = (
    CityDef(
        "Mumbai",
        "MH",
        ("Mumbai", "Mumbai Suburban"),
        ("Bombay", "Greater Mumbai"),
        "Greater Mumbai is exactly the Mumbai City and Mumbai Suburban districts.",
    ),
    CityDef(
        "Pune",
        "MH",
        ("Pune",),
        ("Poona",),
        "Pune city lies within Pune district; the whole district is used, which "
        "is larger than the municipal area.",
    ),
    CityDef("Thane", "MH", ("Thane",), (), "Thane district, larger than the city."),
    CityDef("Nagpur", "MH", ("Nagpur",), (), "Nagpur district, larger than the city."),
    CityDef("Nashik", "MH", ("Nashik",), ("Nasik",), "Nashik district."),
    CityDef(
        "Delhi",
        "DL",
        ("*",),
        ("New Delhi", "NCT of Delhi"),
        "The National Capital Territory: every district inside the Delhi boundary.",
    ),
    CityDef(
        "Bengaluru",
        "KA",
        ("Bangalore",),
        ("Bangalore", "Bengaluru Urban"),
        "Bengaluru Urban district.",
    ),
    CityDef("Mysuru", "KA", ("Mysore",), ("Mysore",), "Mysuru district."),
    CityDef("Chennai", "TN", ("Chennai",), ("Madras",), _WHOLE),
    CityDef("Coimbatore", "TN", ("Coimbatore",), (), "Coimbatore district."),
    CityDef("Madurai", "TN", ("Madurai",), (), "Madurai district."),
    CityDef("Kolkata", "WB", ("Kolkata",), ("Calcutta",), _WHOLE),
    CityDef("Hyderabad", "TS", ("Hydrabad",), (), _WHOLE),
    CityDef("Ahmedabad", "GJ", ("Ahmadabad",), ("Amdavad",), "Ahmedabad district."),
    CityDef("Surat", "GJ", ("Surat",), (), "Surat district."),
    CityDef("Vadodara", "GJ", ("Vadodara",), ("Baroda",), "Vadodara district."),
    CityDef("Jaipur", "RJ", ("Jaipur",), (), "Jaipur district."),
    CityDef("Lucknow", "UP", ("Lucknow",), (), "Lucknow district."),
    CityDef("Kanpur", "UP", ("Kanpur Nagar",), (), "Kanpur Nagar district."),
    CityDef("Varanasi", "UP", ("Varanasi",), ("Benares", "Kashi"), "Varanasi district."),
    CityDef("Agra", "UP", ("Agra",), (), "Agra district."),
    CityDef("Patna", "BR", ("Patna",), (), "Patna district."),
    CityDef("Bhopal", "MP", ("Bhopal",), (), "Bhopal district."),
    CityDef("Indore", "MP", ("Indore",), (), "Indore district."),
    CityDef(
        "Guwahati",
        "AS",
        ("Kamrup Metropolitan",),
        (),
        "Kamrup Metropolitan district, which contains Guwahati.",
    ),
    CityDef(
        "Bhubaneswar",
        "OD",
        ("Khordha",),
        (),
        "Khordha district, which contains the city.",
    ),
    CityDef(
        "Visakhapatnam", "AP", ("Visakhapatnam",), ("Vizag",), "Visakhapatnam district."
    ),
    CityDef("Kochi", "KL", ("Ernakulam",), ("Cochin",), "Ernakulam district."),
    CityDef(
        "Thiruvananthapuram",
        "KL",
        ("Thiruvananthapuram",),
        ("Trivandrum",),
        "Thiruvananthapuram district.",
    ),
    CityDef("Chandigarh", "CH", ("Chandigarh",), (), _WHOLE),
    CityDef("Raipur", "CG", ("Raipur",), (), "Raipur district."),
    CityDef("Ranchi", "JH", ("Ranchi",), (), "Ranchi district."),
    CityDef("Dehradun", "UK", ("Dehradun",), ("Dehra Dun",), "Dehradun district."),
    CityDef("Ludhiana", "PB", ("Ludhiana",), (), "Ludhiana district."),
    CityDef("Srinagar", "JK", ("Srinagar",), (), "Srinagar district."),
)


def _keys(name: str) -> set[str]:
    key = normalise_name(name)
    return {
        normalise_name(k)
        for k in (key, *DISTRICT_ALIASES.get(key, ()), *PLACE_ALIASES.get(key, ()))
    }


def import_cities(db: Session) -> dict:
    """Rebuild the cities table from :data:`CITY_DEFS`. Deterministic."""
    states = {s.code: s for s in db.scalars(select(State))}
    boundaries = list(
        db.scalars(select(AdminBoundary).where(AdminBoundary.level == "district"))
    )
    db.execute(delete(City))

    created = positioned = 0
    for spec in CITY_DEFS:
        state = states.get(spec.state_code)
        if spec.districts == ("*",):
            parts = [b for b in boundaries if state and b.state_id == state.id]
        else:
            wanted = {normalise_name(d) for d in spec.districts}
            parts = [
                b
                for b in boundaries
                if b.normalized_name in wanted
                and (state is None or b.state_id in (None, state.id))
            ]

        cpcb: list[District] = []
        if state is not None:
            names = [p.name for p in parts] or list(spec.districts)
            keys = set().union(*(_keys(n) for n in names)) if names else set()
            cpcb = [
                d
                for d in db.scalars(select(District).where(District.state_id == state.id))
                if normalise_name(d.name) in keys
            ]
            if spec.districts == ("*",):
                cpcb = list(
                    db.scalars(select(District).where(District.state_id == state.id))
                )

        city = City(
            name=spec.name,
            slug=slugify(f"{spec.name}-{spec.state_code}"),
            state_id=state.id if state else None,
            aliases=list(spec.aliases),
            district_ids=sorted(d.id for d in cpcb),
            definition_note=spec.note,
            position_source=(
                "geoBoundaries IND ADM2 district polygons: "
                + ", ".join(p.name for p in parts)
                if parts
                else "No district polygon found; city has no mapped position."
            ),
        )
        if parts:
            city.min_lat = min(p.min_lat for p in parts)
            city.min_lon = min(p.min_lon for p in parts)
            city.max_lat = max(p.max_lat for p in parts)
            city.max_lon = max(p.max_lon for p in parts)
            # The centroid of the largest part: for Mumbai that is the suburban
            # district, which is where most of the city's area is.
            main = max(
                parts, key=lambda p: (p.max_lat - p.min_lat) * (p.max_lon - p.min_lon)
            )
            city.centroid_lat, city.centroid_lon = main.centroid_lat, main.centroid_lon
            positioned += 1
        db.add(city)
        created += 1
    db.commit()
    return {"cities": created, "positioned": positioned}


def find_city(db: Session, text: str) -> City | None:
    """Exact (normalised) match on a city name or alias."""
    key = normalise_name(text)
    if not key:
        return None
    for city in db.scalars(select(City)):
        if key == normalise_name(city.name) or key in {
            normalise_name(a) for a in city.aliases
        }:
            return city
    return None
