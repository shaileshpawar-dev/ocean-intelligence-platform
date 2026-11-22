"""Bulk geometry import: matching, merging, refusals and provenance.

Entirely offline. The "extract" is a small GeoJSON-lines fixture shaped like
the one :mod:`app.water.osm_extract` writes; coordinates are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.models.enums import WaterBodyType
from app.models.water import DataSource, MonitoringStation, WaterBody
from app.models.water_geo import WaterBodyGeometry
from app.water.geometry_import import FeatureIndex, import_geometry, match_body
from sqlalchemy import select


def _feature(element: str, kind: str, name: str, coords, **tags) -> dict:
    geometry = (
        {"type": "LineString", "coordinates": coords}
        if kind == "line"
        else {"type": "Polygon", "coordinates": [coords]}
    )
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return {
        "element": element,
        "kind": kind,
        "names": {"name": name},
        "tags": tags
        or ({"waterway": "river"} if kind == "line" else {"natural": "water"}),
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "geometry": geometry,
    }


@pytest.fixture
def extract(tmp_path: Path) -> Path:
    """An extract holding one river in three segments, two lakes and a decoy."""
    features = [
        # Mithi, three connected segments running north-east.
        _feature("way/1", "line", "Mithi River", [[72.84, 19.04], [72.85, 19.05]]),
        _feature("way/2", "line", "Mithi River", [[72.85, 19.05], [72.86, 19.06]]),
        _feature("way/3", "line", "Mithi River", [[72.86, 19.06], [72.87, 19.07]]),
        # A same-named river 300 km away, not connected to the above.
        _feature("way/9", "line", "Mithi River", [[75.50, 20.50], [75.51, 20.51]]),
        # A lake, and a second lake of the same name nearby.
        _feature(
            "way/20",
            "area",
            "Powai Lake",
            [
                [72.900, 19.120],
                [72.910, 19.120],
                [72.910, 19.130],
                [72.900, 19.130],
                [72.900, 19.120],
            ],
        ),
        _feature(
            "way/21",
            "area",
            "Powai Lake",
            [
                [72.920, 19.120],
                [72.930, 19.120],
                [72.930, 19.130],
                [72.920, 19.130],
                [72.920, 19.120],
            ],
        ),
        # Unrelated name that must never match.
        _feature("way/30", "line", "Dahisar River", [[72.845, 19.045], [72.855, 19.055]]),
    ]
    path = tmp_path / "extract.ndjson"
    with path.open("w", encoding="utf-8") as handle:
        for f in features:
            handle.write(json.dumps(f) + "\n")
    path.with_suffix(".meta.json").write_text(
        json.dumps({"source_file": "test-extract.osm.pbf", "extracted_at": "2026-09-25"}),
        encoding="utf-8",
    )
    return path


def _body(db, name, water_type, stations, slug=None):
    source = db.scalar(select(DataSource)) or DataSource(
        key="t", name="t", organisation="t"
    )
    db.add(source)
    db.flush()
    body = WaterBody(
        slug=slug or name.lower().replace(" ", "-"),
        name=name,
        normalized_name=name.upper(),
        water_type=water_type,
    )
    db.add(body)
    db.flush()
    for i, (lat, lon) in enumerate(stations):
        db.add(
            MonitoringStation(
                station_code=f"{body.slug}:{i}",
                name=f"{name} station {i}",
                slug=f"{body.slug}-{i}",
                source_id=source.id,
                water_body_id=body.id,
                latitude=lat,
                longitude=lon,
            )
        )
    db.commit()
    return body


class TestMatching:
    def test_connected_segments_merge_into_one_course(self, db, extract):
        body = _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        index = FeatureIndex.load(extract)
        stations = list(db.scalars(select(MonitoringStation)))
        outcome = match_body(body, stations, index)
        assert outcome.status == "matched"
        # All three connected segments, and never the distant namesake.
        assert outcome.source_ids == ["way/1", "way/2", "way/3"]
        assert outcome.geometry["type"] == "MultiLineString"
        assert outcome.feature_count == 3

    def test_disconnected_same_name_is_not_joined(self, db, extract):
        body = _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        index = FeatureIndex.load(extract)
        outcome = match_body(body, list(db.scalars(select(MonitoringStation))), index)
        assert "way/9" not in outcome.source_ids

    def test_unrelated_named_feature_is_ignored(self, db, extract):
        body = _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        index = FeatureIndex.load(extract)
        outcome = match_body(body, list(db.scalars(select(MonitoringStation))), index)
        assert "way/30" not in outcome.source_ids

    def test_lake_polygon_matches_station_inside(self, db, extract):
        body = _body(db, "Powai Lake", WaterBodyType.LAKE, [(19.125, 72.905)])
        index = FeatureIndex.load(extract)
        outcome = match_body(body, list(db.scalars(select(MonitoringStation))), index)
        assert outcome.status == "matched"
        assert outcome.source_ids == ["way/20"]
        assert outcome.geometry["type"] == "Polygon"

    def test_equidistant_lakes_are_ambiguous(self, db, extract):
        # Exactly between the two Powai polygons, ~0.5 km from each.
        body = _body(db, "Powai Lake", WaterBodyType.LAKE, [(19.125, 72.915)])
        index = FeatureIndex.load(extract)
        outcome = match_body(body, list(db.scalars(select(MonitoringStation))), index)
        assert outcome.status == "ambiguous"
        assert outcome.geometry is None

    def test_far_station_rejects_the_match(self, db, extract):
        body = _body(db, "Mithi River", WaterBodyType.RIVER, [(19.40, 72.85)])
        index = FeatureIndex.load(extract)
        outcome = match_body(body, list(db.scalars(select(MonitoringStation))), index)
        assert outcome.status == "not_near_stations"

    def test_station_without_coordinates(self, db, extract):
        body = _body(db, "Mithi River", WaterBodyType.RIVER, [])
        db.add(
            MonitoringStation(
                station_code="x",
                name="x",
                slug="x",
                source_id=db.scalar(select(DataSource)).id,
                water_body_id=body.id,
            )
        )
        db.commit()
        index = FeatureIndex.load(extract)
        outcome = match_body(body, list(db.scalars(select(MonitoringStation))), index)
        assert outcome.status == "no_station_coordinates"


class TestStorage:
    def test_import_stores_geometry_with_provenance(self, db, extract):
        _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        summary = import_geometry(db, extract)
        assert summary["matched"] == 1
        row = db.scalar(select(WaterBodyGeometry))
        assert row.source.startswith("OpenStreetMap bulk extract")
        assert row.source_licence.startswith("ODbL")
        assert row.match_method == "bulk_name_and_station_proximity"
        assert row.version == "test-extract.osm.pbf"
        assert row.feature_count == 3
        assert row.clipped is False
        assert row.confidence in {"high", "medium"}
        station = db.scalar(select(MonitoringStation))
        assert station.relationship_type in {"on_geometry", "within_geometry"}
        assert station.geometry_distance_m is not None

    def test_import_is_repeatable(self, db, extract):
        _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        import_geometry(db, extract)
        import_geometry(db, extract)
        assert len(list(db.scalars(select(WaterBodyGeometry)))) == 1

    def test_only_missing_skips_matched_bodies(self, db, extract):
        _body(db, "Mithi River", WaterBodyType.RIVER, [(19.05, 72.85)])
        import_geometry(db, extract)
        again = import_geometry(db, extract, only_missing=True)
        assert again["bodies_considered"] == 0

    def test_no_candidate_clears_stale_geometry(self, db, extract):
        body = _body(db, "Unknown Creek", WaterBodyType.RIVER, [(19.05, 72.85)])
        import_geometry(db, extract)
        assert db.get(WaterBody, body.id).geometry_status == "no_candidates"
        assert db.scalar(select(WaterBodyGeometry)) is None
