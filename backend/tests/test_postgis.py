"""PostGIS: migrations, geometry storage, spatial indexes and spatial SQL.

These tests need a PostgreSQL server with PostGIS. Point ``TEST_POSTGIS_URL``
at one (the local development container works) and they run; otherwise they
skip, so the suite stays green on a machine with only SQLite:

    TEST_POSTGIS_URL=postgresql+psycopg://oip:...@localhost:5433/oip pytest

The fixture creates a throwaway database and runs the real Alembic
migrations into it, so the migration chain itself is under test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

URL = os.environ.get("TEST_POSTGIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_POSTGIS_URL is not set")

TEST_DB = "oip_pytest"
WHEN = datetime(2021, 12, 2, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker]:
    """A throwaway database with the migrations applied."""
    from alembic import command
    from alembic.config import Config

    admin_url = make_url(URL).set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    target_url = make_url(URL).set(database=TEST_DB)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", target_url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "head")

    engine = create_engine(target_url)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def pg(pg_sessionmaker: sessionmaker) -> Iterator[Session]:
    """A session on the migrated test database, cleaned between tests."""
    with pg_sessionmaker() as session:
        session.execute(
            text(
                "TRUNCATE water_body_geometries, monitoring_stations, water_bodies, "
                "admin_boundaries, cities, states, data_sources "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        yield session


class TestMigrations:
    def test_postgis_extension_installed(self, pg: Session):
        assert pg.execute(text("SELECT postgis_version()")).scalar_one()

    def test_geometry_columns_registered(self, pg: Session):
        rows = {
            f"{r[0]}.{r[1]}": r[2]
            for r in pg.execute(
                text(
                    "SELECT f_table_name, f_geometry_column, type FROM geometry_columns "
                    "WHERE f_table_name IN "
                    "('water_body_geometries','monitoring_stations',"
                    "'admin_boundaries','water_bodies','cities','water_images')"
                )
            )
        }
        assert rows["water_body_geometries.geom"] == "GEOMETRY"
        assert rows["monitoring_stations.geom"] == "POINT"
        assert rows["admin_boundaries.geom"] == "MULTIPOLYGON"
        assert rows["cities.extent_geom"] == "MULTIPOLYGON"

    def test_spatial_and_query_indexes_exist(self, pg: Session):
        indexes = {
            r[0]
            for r in pg.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
        }
        assert "ix_water_body_geometries_geom_gist" in indexes
        assert "ix_monitoring_stations_geom_gist" in indexes
        assert "ix_obs_body_param_date" in indexes
        assert "ix_bodies_state_type" in indexes

    def test_gist_index_is_actually_gist(self, pg: Session):
        method = pg.execute(
            text(
                "SELECT am.amname FROM pg_class c "
                "JOIN pg_am am ON am.oid = c.relam "
                "WHERE c.relname = 'ix_monitoring_stations_geom_gist'"
            )
        ).scalar_one()
        assert method == "gist"


class TestGeometryTypes:
    @pytest.mark.parametrize(
        "wkt",
        [
            "POINT(72.85 19.05)",
            "LINESTRING(72.84 19.04, 72.86 19.06)",
            "MULTILINESTRING((72.84 19.04, 72.86 19.06),(72.9 19.1, 72.92 19.12))",
            "POLYGON((78.46 17.41, 78.48 17.41, 78.48 17.43, 78.46 17.43, 78.46 17.41))",
            "MULTIPOLYGON(((78.46 17.41, 78.48 17.41, 78.48 17.43, 78.46 17.41)),"
            "((79.0 18.0, 79.1 18.0, 79.1 18.1, 79.0 18.0)))",
        ],
    )
    def test_every_geometry_type_round_trips(self, pg: Session, wkt: str):
        from app.models.water import WaterBody

        body = WaterBody(slug="b", name="B", normalized_name="B", water_type="river")
        pg.add(body)
        pg.flush()
        body_id = body.id
        pg.execute(
            text(
                "INSERT INTO water_body_geometries "
                "(water_body_id, geometry_type, geojson, min_lat, min_lon, max_lat, "
                " max_lon, source, source_ids, retrieved_at, confidence, match_method, "
                " match_notes, feature_count, clipped, geom, created_at, updated_at) "
                "VALUES (:b, 'x', '{}', 0, 0, 0, 0, 't', '[]', :t, 'high', 'test', "
                "'[]', 1, false, ST_GeomFromText(:wkt, 4326), :t, :t)"
            ),
            {"b": body_id, "t": WHEN, "wkt": wkt},
        )
        pg.commit()
        stored = pg.execute(
            text("SELECT ST_GeometryType(geom), ST_SRID(geom) FROM water_body_geometries")
        ).one()
        assert stored[0].startswith("ST_")
        assert stored[1] == 4326


class TestSpatialQueries:
    def _fixture(self, pg: Session) -> None:
        pg.execute(
            text(
                "INSERT INTO states (id, code, name, slug, created_at, updated_at) "
                "VALUES (1, 'MH', 'Maharashtra', 'maharashtra', :t, :t)"
            ),
            {"t": WHEN},
        )
        pg.execute(
            text(
                "INSERT INTO water_bodies (id, slug, name, normalized_name, water_type, "
                " state_id, centroid_lat, centroid_lon, centroid_geom, match_confidence, "
                " match_method, aliases, source_ids, geometry_status, station_count, "
                " observation_count, created_at, updated_at) VALUES "
                "(1,'mithi','Mithi River','MITHI','river',1,19.05,72.85,"
                " ST_SetSRID(ST_MakePoint(72.85,19.05),4326),1.0,'t','[]','{}',"
                " 'matched',1,1,:t,:t),"
                "(2,'far','Far River','FAR','river',1,25.00,80.00,"
                " ST_SetSRID(ST_MakePoint(80.00,25.00),4326),1.0,'t','[]','{}',"
                " 'matched',1,1,:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.execute(
            text(
                "INSERT INTO water_body_geometries (water_body_id, geometry_type, "
                "geojson, "
                " min_lat, min_lon, max_lat, max_lon, source, source_ids, retrieved_at, "
                " confidence, match_method, match_notes, feature_count, clipped, geom, "
                " created_at, updated_at) VALUES "
                "(1,'LineString','{}',19.04,72.84,19.06,72.86,'osm','[]',:t,'high','t','[]',1,false,"
                " ST_GeomFromText('LINESTRING(72.84 19.04, 72.86 19.06)',4326),:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.execute(
            text(
                "INSERT INTO data_sources (id, key, name, organisation, "
                "expected_cadence, "
                " is_available, created_at, updated_at) "
                "VALUES (1,'t','t','t','monthly',true,:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.execute(
            text(
                "INSERT INTO monitoring_stations (id, station_code, name, slug, "
                "source_id, "
                " water_body_id, state_id, latitude, longitude, geom, geo_quality, "
                " relationship_type, observation_count, created_at, updated_at) VALUES "
                "(1,'S1','Mithi station','s1',1,1,1,19.05,72.85,"
                " ST_SetSRID(ST_MakePoint(72.85,19.05),4326),'ok','on_geometry',1,:t,:t),"
                "(2,'S2','Far station','s2',1,2,1,25.00,80.00,"
                " ST_SetSRID(ST_MakePoint(80.00,25.00),4326),'ok','on_geometry',1,:t,:t)"
            ),
            {"t": WHEN},
        )
        # Maharashtra as a simple box around Mumbai.
        pg.execute(
            text(
                "INSERT INTO admin_boundaries (level, name, normalized_name, state_id, "
                " geojson, min_lat, min_lon, max_lat, max_lon, centroid_lat, "
                "centroid_lon, "
                " source, source_id, licence, geom, created_at, updated_at) VALUES "
                "('state','Maharashtra','MAHARASHTRA',1,'{}',18.0,72.0,20.0,74.0,19.0,73.0,"
                " 'test','IN-MH','test',"
                " ST_Multi(ST_MakeEnvelope(72.0,18.0,74.0,20.0,4326)),:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.execute(
            text(
                "INSERT INTO cities (id, name, slug, state_id, aliases, district_ids, "
                " min_lat, min_lon, max_lat, max_lon, position_source, definition_note, "
                " extent_geom, created_at, updated_at) VALUES "
                "(1,'Mumbai','mumbai-mh',1,'[]','[]',18.9,72.8,19.3,73.0,'test','test',"
                " ST_Multi(ST_MakeEnvelope(72.8,18.9,73.0,19.3,4326)),:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.commit()

    def test_bounding_box_query(self, pg: Session):
        self._fixture(pg)
        ids = [
            r[0]
            for r in pg.execute(
                text(
                    "SELECT water_body_id FROM water_body_geometries "
                    "WHERE geom && ST_MakeEnvelope(72.7, 18.9, 73.1, 19.3, 4326)"
                )
            )
        ]
        assert ids == [1]

    def test_radius_query_is_a_circle_in_metres(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        rows = pg.execute(
            text(
                """
                SELECT id, ST_Distance(
                           centroid_geom::geography,
                           ST_SetSRID(ST_MakePoint(72.85, 19.05), 4326)::geography
                       ) / 1000.0 AS km
                  FROM water_bodies
                 WHERE ST_DWithin(
                           centroid_geom::geography,
                           ST_SetSRID(ST_MakePoint(72.85, 19.05), 4326)::geography,
                           25000
                       )
                 ORDER BY km
                """
            )
        ).all()
        assert [int(r[0]) for r in rows] == [1]
        assert rows[0][1] == pytest.approx(0.0, abs=0.01)
        assert spatial.available(pg) is True

    def test_intersection_and_state_containment(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        assert spatial.state_containing(pg, 19.05, 72.85) == "MH"
        assert spatial.state_containing(pg, 25.0, 80.0) is None
        intersects = pg.execute(
            text(
                "SELECT COUNT(*) FROM water_body_geometries g JOIN admin_boundaries b "
                "ON ST_Intersects(g.geom, b.geom) WHERE b.level = 'state'"
            )
        ).scalar_one()
        assert intersects == 1

    def test_station_to_water_body_association_by_distance(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        metres = spatial.station_distance_to_geometry(pg, station_id=1, water_body_id=1)
        assert metres is not None and metres < 50
        rows = pg.execute(
            text(
                """
                SELECT s.id, g.water_body_id,
                       ST_Distance(s.geom::geography, g.geom::geography) AS m
                  FROM monitoring_stations s
                  JOIN water_body_geometries g
                    ON ST_DWithin(s.geom::geography, g.geom::geography, 2000)
                 ORDER BY s.id
                """
            )
        ).all()
        # Only the Mithi station is within 2 km of the Mithi geometry.
        assert [(int(r[0]), int(r[1])) for r in rows] == [(1, 1)]

    def test_city_extent_distance_is_zero_inside(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        near = spatial.bodies_near_city(pg, city_id=1, radius_km=25)
        assert near is not None
        assert near[0][0] == 1
        assert near[0][1] == 0.0  # inside the city extent

    def test_station_clusters_group_in_sql(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        groups = spatial.station_clusters(pg, None, cell_degrees=10.0)
        assert groups is not None
        assert sum(g["count"] for g in groups) == 2

    def test_proximity_does_not_depend_on_the_sync_job(self, pg: Session):
        """A body ingested since the last sync-geometry is still found.

        ``centroid_geom`` is derived by ``db sync-geometry``; the lat/lon
        columns are written at ingest. The staging smoke test caught the
        earlier behaviour: a fresh stack with real data answered "nothing
        near here" until a geometry job had run.
        """
        self._fixture(pg)
        from app.services import spatial

        # Exactly what an ingest leaves behind: a position, no derived column.
        pg.execute(
            text(
                "INSERT INTO water_bodies (id, slug, name, normalized_name, "
                " water_type, state_id, centroid_lat, centroid_lon, "
                " match_confidence, match_method, aliases, source_ids, "
                " geometry_status, station_count, observation_count, created_at, "
                " updated_at) VALUES "
                "(3,'just-ingested','Just Ingested River','JUST INGESTED','river',"
                " 1,19.06,72.86,1.0,'t','[]','{}','unmatched',1,1,:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.flush()
        assert pg.execute(
            text("SELECT centroid_geom IS NULL FROM water_bodies WHERE id = 3")
        ).scalar_one(), "fixture must have no derived geometry"

        found = spatial.bodies_within_radius(pg, 19.05, 72.85, 25.0)
        assert found is not None
        assert 3 in [i for i, _ in found], "ingested body must be within 25 km"
        assert 2 not in [i for i, _ in found], "the far river is still excluded"
        distance = next(km for i, km in found if i == 3)
        assert distance == pytest.approx(1.5, abs=0.5)

    def test_stations_near_city_do_not_depend_on_the_sync_job(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        pg.execute(
            text(
                "INSERT INTO monitoring_stations (id, station_code, name, slug, "
                " source_id, water_body_id, state_id, latitude, longitude, "
                " relationship_type, geo_quality, observation_count, created_at, "
                " updated_at) VALUES "
                "(9,'MH:NEW','New Station','new-station',1,1,1,19.05,72.85,"
                " 'name_match','ok',1,:t,:t)"
            ),
            {"t": WHEN},
        )
        pg.flush()
        near = spatial.stations_near_city(pg, city_id=1, radius_km=25)
        assert near is not None
        assert 9 in [i for i, _ in near]

    def test_derived_geometry_is_valid_even_when_the_source_is_not(self, pg: Session):
        """A self-intersecting OSM polygon must not break spatial queries.

        `geometry-qa --fix` used to repair the derived column, and the next
        `db sync-geometry` re-derived it from the GeoJSON and put the flaw
        back. Validity belongs in the derivation; the stored GeoJSON stays as
        retrieved and the QA report still names the source as invalid.
        """
        self._fixture(pg)
        from app.db.transfer import sync_geometry

        bowtie = (
            '{"type":"Polygon","coordinates":'
            "[[[72.80,19.00],[72.90,19.10],[72.90,19.00],[72.80,19.10],"
            "[72.80,19.00]]]}"
        )
        pg.execute(
            text(
                "INSERT INTO water_body_geometries (water_body_id, geometry_type, "
                " geojson, min_lat, min_lon, max_lat, max_lon, source, source_ids, "
                " retrieved_at, confidence, match_method, match_notes, feature_count, "
                " clipped, created_at, updated_at) VALUES "
                "(2,'Polygon',:gj,19.00,72.80,19.10,72.90,'osm','[]',:t,'high','t',"
                " '[]',1,false,:t,:t)"
            ),
            {"gj": bowtie, "t": WHEN},
        )
        pg.commit()

        assert not pg.execute(
            text("SELECT ST_IsValid(ST_GeomFromGeoJSON(:gj))"), {"gj": bowtie}
        ).scalar_one(), "the fixture must be an invalid polygon"

        sync_geometry(pg)

        assert pg.execute(
            text(
                "SELECT ST_IsValid(geom) FROM water_body_geometries "
                "WHERE water_body_id = 2"
            )
        ).scalar_one(), "the derived geometry must be usable"
        assert (
            pg.execute(
                text("SELECT geojson FROM water_body_geometries WHERE water_body_id = 2")
            ).scalar_one()
            == bowtie
        ), "the stored GeoJSON is the provenance copy and must not be rewritten"

        from app.water.geometry_qa import run_checks

        report = run_checks(pg)
        checks = set(report["by_check"])
        assert "invalid_source_geometry" in checks
        assert "invalid_geometry" not in checks

    def test_a_station_is_identified_by_the_river_it_stands_on(self, pg: Session):
        """When the label names no water body, the coordinates decide.

        CPCB's real-time stations are named for the place -- "Road Bridge on
        Gandak, Hajipur", "Sahebganj" -- so reading the label literally
        invented water bodies called "Road". A station 100 m from the mapped
        Mithi is on the Mithi, and the distance is recorded so the claim can
        be checked.
        """
        self._fixture(pg)
        from app.services import spatial

        # The Mithi's geometry in the fixture runs from (72.84,19.04) to
        # (72.86,19.06). A point beside it:
        found = spatial.nearest_mapped_body(pg, 19.0405, 72.8405)
        assert found is not None
        body_id, metres = found
        assert body_id == 1, "the mapped Mithi, not the far river"
        assert metres < 200

    def test_nothing_is_claimed_when_no_geometry_is_near(self, pg: Session):
        """Two of the forty real-time stations are like this; they stay unresolved."""
        self._fixture(pg)
        from app.services import spatial

        assert spatial.nearest_mapped_body(pg, 22.0, 79.0) is None

    def test_the_search_radius_is_honoured(self, pg: Session):
        self._fixture(pg)
        from app.services import spatial

        far_point = (19.20, 72.84)  # ~18 km north of the Mithi fixture
        assert spatial.nearest_mapped_body(pg, *far_point, max_metres=1000) is None
        assert spatial.nearest_mapped_body(pg, *far_point, max_metres=30000) is not None
