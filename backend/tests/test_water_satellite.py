"""Satellite evidence: scene acceptance and proxy labelling, without network.

Scene ids, histograms and statistics are fixtures shaped like the Planetary
Computer responses, not real acquisitions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from app.models.enums import WaterBodyType
from app.models.water import WaterBody
from app.models.water_geo import WaterBodyGeometry, WaterImage
from app.water.satellite import (
    MAX_CLOUD_FRACTION,
    PROXY_LABEL,
    fetch_imagery,
    find_scene,
    images_for,
)
from sqlalchemy import func, select

NOW = datetime(2026, 9, 21, tzinfo=UTC)
LAKE = {
    "type": "Polygon",
    "coordinates": [
        [[78.46, 17.41], [78.48, 17.41], [78.48, 17.43], [78.46, 17.43], [78.46, 17.41]]
    ],
}
BIG_TILE = {
    "type": "Polygon",
    "coordinates": [
        [[78.0, 17.0], [79.0, 17.0], [79.0, 18.0], [78.0, 18.0], [78.0, 17.0]]
    ],
}
HALF_TILE = {
    "type": "Polygon",
    "coordinates": [
        [[78.47, 17.0], [79.0, 17.0], [79.0, 18.0], [78.47, 18.0], [78.47, 17.0]]
    ],
}


def _item(item_id: str, date: str, footprint: dict, cloud: float = 2.0) -> dict:
    return {
        "id": item_id,
        "geometry": footprint,
        "properties": {
            "datetime": f"{date}T05:06:49Z",
            "eo:cloud_cover": cloud,
            "s2:mgrs_tile": "43QHV",
        },
    }


def _scl(water: int, cloud: int, other: int) -> dict:
    return {"histogram": [[other, water, cloud], [4.0, 6.0, 10.0]]}


def _stats_for(scl_by_item: dict):
    def stats(item_id: str, feature: dict, params: dict) -> dict:
        if params.get("assets") == "SCL":
            return scl_by_item[item_id]
        return {"median": 0.0412, "mean": 0.0398, "count": 5000}

    return stats


def _body() -> WaterBody:
    return WaterBody(id=1, name="Test Lake", water_type=WaterBodyType.LAKE)


class TestSceneAcceptance:
    def test_newest_clear_scene_is_chosen_after_rejections(self):
        items = [
            _item("partial", "2026-09-10", HALF_TILE),
            _item("cirrus", "2026-08-20", BIG_TILE, cloud=1.0),
            _item("shore", "2026-08-01", BIG_TILE),
            _item("clear", "2026-07-15", BIG_TILE),
        ]
        scl = {
            # Tile says 1% cloud, but the lake itself is under cirrus.
            "cirrus": _scl(water=300, cloud=4700, other=0),
            "shore": _scl(water=500, cloud=0, other=500),
            "clear": _scl(water=950, cloud=10, other=40),
        }
        outcome = find_scene(
            _body(), LAKE, now=NOW, search=lambda *a: items, stats=_stats_for(scl)
        )
        assert outcome.status == "retrieved"
        assert outcome.image.scene_id == "clear"
        reasons = {t["scene_id"]: t.get("rejected", "") for t in outcome.tried}
        assert "does not contain the whole" in reasons["partial"]
        assert "cloud or cirrus" in reasons["cirrus"]
        assert "classified as water" in reasons["shore"]

    def test_proxy_is_labelled_uncalibrated_and_unitless(self):
        items = [_item("clear", "2026-07-15", BIG_TILE)]
        outcome = find_scene(
            _body(),
            LAKE,
            now=NOW,
            search=lambda *a: items,
            stats=_stats_for({"clear": _scl(950, 0, 50)}),
        )
        proxy = outcome.image.image_metadata["proxy"]
        assert proxy["evidence_type"] == "SATELLITE_OBSERVED"
        assert proxy["label"] == PROXY_LABEL
        assert proxy["calibrated"] is False and proxy["unit"] is None
        assert "not a turbidity measurement" in proxy["caveat"]
        assert outcome.image.evidence_type == "SATELLITE"
        assert outcome.image.thumbnail_url.endswith("assets=visual")

    def test_no_clear_scene_is_reported_not_forced(self):
        items = [_item("cloudy", "2026-08-01", BIG_TILE)]
        outcome = find_scene(
            _body(),
            LAKE,
            now=NOW,
            search=lambda *a: items,
            stats=_stats_for({"cloudy": _scl(100, 900, 0)}),
        )
        assert outcome.status == "no_scene"
        assert outcome.image is None

    def test_cloud_threshold_is_strict(self):
        assert MAX_CLOUD_FRACTION <= 0.05

    def test_search_failure_is_a_source_error(self):
        def failing(*a: object) -> list[dict]:
            raise httpx.ConnectError("down")

        outcome = find_scene(_body(), LAKE, now=NOW, search=failing)
        assert outcome.status == "source_error"


class TestImageryStorage:
    def _lake(self, db, geometry: dict | None):
        body = WaterBody(
            slug="test-lake",
            name="Test Lake",
            normalized_name="TEST LAKE",
            water_type=WaterBodyType.LAKE,
        )
        db.add(body)
        db.flush()
        if geometry is not None:
            db.add(
                WaterBodyGeometry(
                    water_body_id=body.id,
                    geometry_type=geometry["type"],
                    geojson=json.dumps(geometry),
                    min_lat=17.41,
                    min_lon=78.46,
                    max_lat=17.43,
                    max_lon=78.48,
                    source="test",
                    source_ids=[],
                    retrieved_at=NOW,
                    confidence="high",
                    match_method="test",
                )
            )
        db.commit()
        return body

    def test_river_line_is_not_attempted(self, db):
        line = {"type": "LineString", "coordinates": [[78.46, 17.41], [78.48, 17.43]]}
        body = self._lake(db, line)
        assert fetch_imagery(db, body).status == "no_polygon"

    def test_stored_once_per_scene_and_listed(self, db):
        body = self._lake(db, LAKE)
        items = [_item("clear", "2026-07-15", BIG_TILE)]
        kwargs = {
            "now": NOW,
            "search": lambda *a: items,
            "stats": _stats_for({"clear": _scl(950, 0, 50)}),
        }
        fetch_imagery(db, body, **kwargs)
        fetch_imagery(db, body, **kwargs)
        assert db.scalar(select(func.count(WaterImage.id))) == 1
        listed = images_for(db, body)
        assert listed[0]["acquisition_date"] == "2026-07-15"
        assert listed[0]["proxy"]["median"] == 0.0412
