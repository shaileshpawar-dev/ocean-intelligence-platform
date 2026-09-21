"""Geospatial foundation: geometry helpers, OSM matching, boundaries, cities.

No network: Overpass responses and boundary files are small fixtures shaped
like the real ones. Coordinates are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.models.enums import WaterBodyType
from app.models.water import DataSource, District, MonitoringStation, State, WaterBody
from app.models.water_geo import (
    AdminBoundary,
    City,
    ReferenceStandard,
    ReferenceThreshold,
    WaterBodyGeometry,
)
from app.water import geo
from app.water.boundaries import import_boundaries, state_boundary
from app.water.cities import find_city, import_cities
from app.water.geometry import (
    OSM_LICENCE,
    POLICIES,
    build_query,
    element_geometry,
    fetch_and_store,
    match_geometry,
    name_cores,
)
from app.water.reference_catalog import ALL_STANDARDS
from app.water.reference_seed import seed_reference_standards
from sqlalchemy import func, select

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


# ---------------------------------------------------------------------------
class TestGeometryHelpers:
    def test_bbox_and_centroid_of_square(self):
        assert geo.bbox(SQUARE) == (0, 0, 2, 2)
        assert geo.centroid(SQUARE) == pytest.approx((1.0, 1.0))

    def test_point_in_polygon_respects_holes(self):
        holed = {
            "type": "Polygon",
            "coordinates": [
                SQUARE["coordinates"][0],
                [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]],
            ],
        }
        assert geo.contains_point(SQUARE, 1, 1)
        assert not geo.contains_point(holed, 1, 1)
        assert geo.contains_point(holed, 0.2, 0.2)
        assert not geo.contains_point(SQUARE, 3, 3)

    def test_distance_to_line_is_perpendicular(self):
        line = {"type": "LineString", "coordinates": [[72.80, 19.0], [72.90, 19.0]]}
        # 0.01 degrees of latitude is ~1.11 km.
        assert geo.distance_km(line, 72.85, 19.01) == pytest.approx(1.11, abs=0.02)
        assert geo.distance_km(SQUARE, 1, 1) == 0.0

    def test_clip_keeps_only_inside_runs(self):
        line = {
            "type": "LineString",
            "coordinates": [[0, 0], [1, 0], [2, 0], [5, 0], [6, 0]],
        }
        clipped = geo.clip_lines(line, (-0.5, -1, 2.5, 1))
        assert clipped == {"type": "LineString", "coordinates": [[0, 0], [1, 0], [2, 0]]}
        assert geo.clip_lines(line, (10, 10, 11, 11)) is None

    def test_overlapping_windows_merge(self):
        merged = geo.merge_boxes([(0, 0, 2, 2), (1, 1, 3, 3), (10, 10, 11, 11)])
        assert sorted(merged) == [(0, 0, 3, 3), (10, 10, 11, 11)]

    def test_rounding_drops_repeated_vertices(self):
        line = {
            "type": "LineString",
            "coordinates": [[1.000001, 2.0], [1.000002, 2.0], [3, 4]],
        }
        assert geo.round_geometry(line, 4)["coordinates"] == [[1.0, 2.0], [3, 4]]


# ---------------------------------------------------------------------------
def _source(db) -> DataSource:
    src = DataSource(key="t", name="Test", organisation="Test")
    db.add(src)
    db.flush()
    return src


def _body(db, name, water_type, stations, aliases=()):
    src = _source(db)
    body = WaterBody(
        slug=name.lower().replace(" ", "-"),
        name=name,
        normalized_name=name.upper(),
        water_type=water_type,
        aliases=list(aliases),
    )
    db.add(body)
    db.flush()
    for i, (lat, lon) in enumerate(stations):
        db.add(
            MonitoringStation(
                station_code=f"T:{name}:{i}",
                name=f"{name} station {i}",
                slug=f"{body.slug}-{i}",
                source_id=src.id,
                water_body_id=body.id,
                latitude=lat,
                longitude=lon,
            )
        )
    db.commit()
    return body


def _way(osm_id, coords, **tags):
    return {
        "type": "way",
        "id": osm_id,
        "tags": tags,
        "geometry": [{"lat": lat, "lon": lon} for lon, lat in coords],
    }


def _lake(osm_id, lon, lat, half=0.002, name="Powai Lake"):
    ring = [
        (lon - half, lat - half),
        (lon + half, lat - half),
        (lon + half, lat + half),
        (lon - half, lat + half),
        (lon - half, lat - half),
    ]
    return _way(osm_id, ring, natural="water", name=name)


class TestOsmMatching:
    def test_type_words_are_not_searched_for(self):
        body = WaterBody(name="Mithi River", aliases=["Mithi Nallah"])
        assert name_cores(body) == ["MITHI"]

    def test_query_is_windowed_and_name_filtered(self):
        q = build_query(POLICIES["line"], ["MITHI"], [(72.8, 19.0, 72.9, 19.1)])
        assert "(19.00000,72.80000,19.10000,72.90000)" in q
        assert '"name"~"^(mithi)' in q
        assert "out tags geom" in q

    def test_relation_rings_are_assembled(self):
        rel = {
            "type": "relation",
            "id": 1,
            "tags": {"natural": "water"},
            "members": [
                {
                    "type": "way",
                    "role": "outer",
                    "geometry": [
                        {"lon": 0, "lat": 0},
                        {"lon": 1, "lat": 0},
                        {"lon": 1, "lat": 1},
                    ],
                },
                {
                    "type": "way",
                    "role": "outer",
                    "geometry": [
                        {"lon": 1, "lat": 1},
                        {"lon": 0, "lat": 1},
                        {"lon": 0, "lat": 0},
                    ],
                },
            ],
        }
        g = element_geometry(rel)
        assert g["type"] == "Polygon"
        assert g["coordinates"][0][0] == g["coordinates"][0][-1]

    def test_river_matched_near_stations_is_high_confidence(self, db):
        body = _body(
            db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85), (19.07, 72.87)]
        )
        river = _way(
            10,
            [(72.84, 19.04), (72.86, 19.06), (72.88, 19.08)],
            waterway="river",
            name="Mithi River",
        )
        payload = {
            "elements": [river],
            "osm3s": {"timestamp_osm_base": "2026-09-20T00:00:00Z"},
        }
        outcome = fetch_and_store(db, body, fetch=lambda q: payload)
        assert outcome.status == "matched"
        assert outcome.confidence == "high"
        row = db.scalar(select(WaterBodyGeometry))
        assert row.geometry_type == "LineString"
        assert row.source_ids == ["way/10"]
        assert row.source_licence == OSM_LICENCE
        assert row.version == "2026-09-20T00:00:00Z"
        assert row.clipped is True
        stations = db.scalars(select(MonitoringStation)).all()
        assert {s.relationship_type for s in stations} == {"on_geometry"}
        assert all(s.geometry_distance_m is not None for s in stations)
        assert db.get(WaterBody, body.id).geometry_status == "matched"

    def test_same_name_far_from_stations_is_rejected(self, db):
        body = _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        far = _way(11, [(72.95, 19.05), (72.96, 19.06)], waterway="river", name="Mithi")
        outcome = fetch_and_store(db, body, fetch=lambda q: {"elements": [far]})
        assert outcome.status == "not_near_stations"
        assert db.scalar(select(func.count(WaterBodyGeometry.id))) == 0

    def test_equidistant_lakes_are_ambiguous_not_guessed(self, db):
        stations = [MonitoringStation(id=1, name="s", latitude=19.12, longitude=72.905)]
        body = WaterBody(name="Powai Lake", water_type=WaterBodyType.LAKE, aliases=[])
        # Two lakes, station exactly between them.
        payload = {
            "elements": [_lake(1, 72.900, 19.12, 0.001), _lake(2, 72.910, 19.12, 0.001)]
        }
        outcome = match_geometry(body, stations, fetch=lambda q: payload)
        assert outcome.status == "ambiguous"
        assert outcome.geometry is None

    def test_station_inside_lake_is_within_geometry(self, db):
        body = _body(db, "Powai Lake", WaterBodyType.LAKE, [(19.127, 72.905)])
        payload = {"elements": [_lake(5, 72.905, 19.127)]}
        outcome = fetch_and_store(db, body, fetch=lambda q: payload)
        assert outcome.status == "matched"
        assert outcome.geometry["type"] == "Polygon"
        station = db.scalar(select(MonitoringStation))
        assert station.relationship_type == "within_geometry"
        assert station.geometry_distance_m == 0

    def test_unsupported_type_and_missing_coordinates(self, db):
        groundwater = WaterBody(name="Well X", water_type=WaterBodyType.GROUNDWATER)
        assert match_geometry(groundwater, []).status == "unsupported_type"
        lake = WaterBody(name="Powai Lake", water_type=WaterBodyType.LAKE, aliases=[])
        unlocated = [MonitoringStation(id=1, name="s", latitude=None, longitude=None)]
        assert match_geometry(lake, unlocated).status == "no_station_coordinates"

    def test_source_error_keeps_previous_geometry(self, db):
        body = _body(db, "Powai Lake", WaterBodyType.LAKE, [(19.127, 72.905)])
        fetch_and_store(
            db, body, fetch=lambda q: {"elements": [_lake(5, 72.905, 19.127)]}
        )

        def failing(q):
            import httpx

            raise httpx.ConnectError("down")

        outcome = fetch_and_store(db, body, fetch=failing)
        assert outcome.status == "source_error"
        assert db.scalar(select(func.count(WaterBodyGeometry.id))) == 1


# ---------------------------------------------------------------------------
def _feature(props, coords):
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


@pytest.fixture
def boundary_files(tmp_path: Path) -> tuple[Path, Path]:
    adm1 = {
        "type": "FeatureCollection",
        "features": [
            _feature(
                {"shapeName": "Mahārāshtra", "shapeISO": "IN-MH"}, _box(72, 18, 74, 20)
            ),
            _feature(
                {"shapeName": "Telangāna", "shapeISO": "IN-TG"}, _box(74, 18, 76, 20)
            ),
        ],
    }
    adm2 = {
        "type": "FeatureCollection",
        "features": [
            _feature(
                {"shapeName": "Mumbai", "shapeID": "d1"}, _box(72.8, 18.9, 72.9, 19.0)
            ),
            _feature(
                {"shapeName": "Mumbai Suburban", "shapeID": "d2"},
                _box(72.8, 19.0, 73.0, 19.3),
            ),
            # Mostly in Telangana, but its centroid pokes into Maharashtra: the
            # vertex vote must still assign it to Telangana.
            _feature(
                {"shapeName": "Hydrabad", "shapeID": "d3"},
                [[73.9, 18.5], [75.5, 18.5], [75.5, 19.5], [74.1, 19.5], [73.9, 18.5]],
            ),
        ],
    }
    p1, p2 = tmp_path / "adm1.geojson", tmp_path / "adm2.geojson"
    p1.write_text(json.dumps(adm1), encoding="utf-8")
    p2.write_text(json.dumps(adm2), encoding="utf-8")
    return p1, p2


class TestBoundariesAndCities:
    def _states(self, db):
        mh = State(code="MH", name="Maharashtra", slug="maharashtra")
        ts = State(code="TS", name="Telangana", slug="telangana")
        db.add_all([mh, ts])
        db.flush()
        db.add(District(state_id=mh.id, name="Mumbai Suburban", slug="mumbai-suburban"))
        db.add(District(state_id=ts.id, name="Hyderabad", slug="hyderabad"))
        db.commit()
        return mh, ts

    def test_iso_codes_link_to_cpcb_states(self, db, boundary_files):
        mh, ts = self._states(db)
        result = import_boundaries(
            db, state_path=boundary_files[0], district_path=boundary_files[1]
        )
        assert result["states_linked"] == 2
        # IN-TG in the boundary file is TS in CPCB's file names.
        assert state_boundary(db, ts).name == "Telangana"
        assert state_boundary(db, mh).name == "Maharashtra"  # accents folded
        assert result["districts_without_parent"] == 0

    def test_district_parent_by_vertex_vote(self, db, boundary_files):
        _, ts = self._states(db)
        import_boundaries(
            db, state_path=boundary_files[0], district_path=boundary_files[1]
        )
        hyd = db.scalar(select(AdminBoundary).where(AdminBoundary.name == "Hydrabad"))
        assert hyd.state_id == ts.id
        assert hyd.district_id is not None  # linked to CPCB "Hyderabad" via alias

    def test_cities_are_district_groupings_with_positions(self, db, boundary_files):
        mh, _ = self._states(db)
        import_boundaries(
            db, state_path=boundary_files[0], district_path=boundary_files[1]
        )
        import_cities(db)
        mumbai = find_city(db, "Bombay")
        assert mumbai is not None and mumbai.name == "Mumbai"
        assert mumbai.state_id == mh.id
        assert "Mumbai Suburban" in mumbai.position_source
        assert mumbai.min_lat == pytest.approx(18.9) and mumbai.max_lat == pytest.approx(
            19.3
        )
        assert len(mumbai.district_ids) == 1  # only the CPCB district that exists
        assert "Mumbai City and Mumbai Suburban" in mumbai.definition_note

    def test_city_without_polygon_has_no_invented_position(self, db, boundary_files):
        self._states(db)
        import_boundaries(
            db, state_path=boundary_files[0], district_path=boundary_files[1]
        )
        import_cities(db)
        pune = db.scalar(select(City).where(City.name == "Pune"))
        assert pune.centroid_lat is None
        assert "no mapped position" in pune.position_source


# ---------------------------------------------------------------------------
class TestReferenceSeed:
    def test_seed_is_idempotent_and_complete(self, db):
        seed_reference_standards(db)
        seed_reference_standards(db)
        assert db.scalar(select(func.count(ReferenceStandard.id))) == len(ALL_STANDARDS)
        expected = sum(len(s.thresholds) for s in ALL_STANDARDS)
        assert db.scalar(select(func.count(ReferenceThreshold.id))) == expected
        bathing = db.scalar(
            select(ReferenceStandard).where(ReferenceStandard.code == "EP1986-93-BATHING")
        )
        fc = next(t for t in bathing.thresholds if t.parameter == "fecal_coliform")
        assert (fc.maximum, fc.desirable) == (2500, 500)
        assert bathing.source_url.startswith("https://cpcb.nic.in/")


class TestCoverage:
    def test_report_counts_and_flags_empty_states(self, db):
        from app.water.coverage import coverage_report, render_markdown

        db.add(State(code="GA", name="Goa", slug="goa"))
        db.commit()
        report = coverage_report(db)
        t = report["totals"]
        assert t["states_available_in_source"] == 35
        assert t["states_loaded"] == 0
        assert "GA" in t["states_without_data"]
        goa = next(r for r in report["states"] if r["code"] == "GA")
        assert goa["loaded"] is False and goa["note"]
        text = render_markdown(report)
        assert "| GA | Goa |" in text
        assert "nothing here is estimated" in text
