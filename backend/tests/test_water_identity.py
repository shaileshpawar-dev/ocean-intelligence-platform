"""Regression tests for canonical water-body identity.

Station labels mix three different things: the water body, where on it the
sample was taken, and the nearest place. Only the first may define identity.
These tests run the real ingestion pipeline over station names shaped like the
published ones and assert that sampling positions never split a water body,
that spelling variants and local drain names converge, and that same-named
features far apart stay separate.

Station names and values here are test fixtures, not observations.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.models.enums import WaterBodyType
from app.models.water import MonitoringStation, WaterBody
from app.water import providers as provider_registry
from app.water.freshness import Cadence
from app.water.ingestion import ingest_provider
from app.water.matching import resolve, sampling_descriptor
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    WaterDataProvider,
)
from sqlalchemy import func, select

WHEN = datetime(2021, 12, 2, 8, 30, tzinfo=UTC)


def _row(station: str, lat: float, lon: float, state: str, code: str) -> ObservationRow:
    return ObservationRow(
        station_name=station,
        parameter_key="bod",
        observed_at=WHEN,
        value=4.0,
        normalized_value=4.0,
        unit="mg/L",
        normalized_unit="mg/L",
        latitude=lat,
        longitude=lon,
        state_name=state,
        state_code=code,
        district="Test",
        source_reference=f"test:{station}",
    )


ROWS = [
    # Mithi: one river, many sampling positions, and a local drain name.
    _row("MITHI RIVER MAHIM BANDRA MUMBAI", 19.05, 72.85, "Maharashtra", "MH"),
    _row("MITHI RIVER D/S", 19.06, 72.86, "Maharashtra", "MH"),
    _row("MITHI RIVER U/S OF KURLA", 19.07, 72.87, "Maharashtra", "MH"),
    _row("MITHI RIVER MIDSTREAM", 19.065, 72.865, "Maharashtra", "MH"),
    _row("MITHI NALLAH AT KURLA", 19.08, 72.88, "Maharashtra", "MH"),
    # Yamuna across two states, one without the keyword.
    _row("YAMUNA RIVER AT MATHURA", 27.49, 77.67, "Uttar Pradesh", "UP"),
    _row("YAMUNA AT NIZAMUDDIN BRIDGE", 28.59, 77.26, "Delhi", "DL"),
    _row("YAMUNA D/S OF OKHLA BARRAGE", 28.54, 77.31, "Delhi", "DL"),
    # Ganga at two positions in one state.
    _row(
        "RIVER GANGA AT MADHYA GANGA BARRAGE BIJNOR", 29.37, 78.03, "Uttar Pradesh", "UP"
    ),
    _row("RIVER GANGA D/S NEAR CREMATION GHAT", 29.30, 78.10, "Uttar Pradesh", "UP"),
    # Spelling variants of one river.
    _row("BRAHAMPUTRA RIVER AT BOGIBEEL BRIDGE", 27.42, 94.76, "Assam", "AS"),
    _row("BRAHMAPUTRA AT GUWAHATI", 26.19, 91.75, "Assam", "AS"),
    # Same lake name in two states: must stay two lakes.
    _row("RANI TALAB", 22.3, 73.2, "Gujarat", "GJ"),
    _row("RANI TALAB", 25.4, 81.8, "Uttar Pradesh", "UP"),
    # Same river name far apart (> 500 km): must stay two rivers.
    _row("AMRAVATI RIVER AT DHARAPURAM", 10.73, 77.52, "Tamil Nadu", "TN"),
    _row("AMRAVATI RIVER AT DADHAL", 21.6, 73.0, "Gujarat", "GJ"),
]


class _Provider(WaterDataProvider):
    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="cpcb_nwdp", name="test", organisation="test", cadence=Cadence.MONTHLY
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        # Two resources, so cross-resource reconciliation is exercised.
        return [
            FetchPlan(identifier="a", description="a"),
            FetchPlan(identifier="b", description="b"),
        ]

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        half = len(ROWS) // 2
        yield from ROWS[:half] if plan.identifier == "a" else ROWS[half:]


@pytest.fixture
def identity_db(db, monkeypatch):
    monkeypatch.setitem(provider_registry.PROVIDERS, "cpcb_nwdp", _Provider)
    ingest_provider(db, "cpcb_nwdp")
    return db


def _bodies(db, core: str) -> list[WaterBody]:
    return db.query(WaterBody).filter(WaterBody.normalized_name == core).all()


class TestSamplingPositionsNeverSplitBodies:
    def test_mithi_is_one_river(self, identity_db):
        mithi = _bodies(identity_db, "MITHI")
        assert len(mithi) == 1
        assert mithi[0].name == "Mithi River"
        assert mithi[0].station_count == 5

    def test_positions_are_kept_on_stations(self, identity_db):
        descriptors = {
            s.name: s.position_descriptor
            for s in identity_db.query(MonitoringStation).all()
        }
        assert descriptors["MITHI RIVER D/S"] == "D/S"
        assert descriptors["MITHI RIVER U/S OF KURLA"] == "U/S Of Kurla"
        assert descriptors["MITHI RIVER MIDSTREAM"] == "Midstream"

    @pytest.mark.parametrize(
        "station",
        [
            "MITHI RIVER D/S",
            "MITHI RIVER U/S OF KURLA",
            "MITHI RIVER MIDSTREAM",
            "MITHI RIVER AT KALINA",
            "MITHI RIVER DOWNSTREAM",
            "MITHI RIVER UPSTREAM",
        ],
    )
    def test_position_words_never_enter_the_name(self, station):
        assert resolve(station).name == "Mithi River"

    def test_ganga_positions_share_one_body(self, identity_db):
        ganga = _bodies(identity_db, "GANGA")
        assert len(ganga) == 1
        assert ganga[0].station_count == 2


class TestNamesConverge:
    def test_local_drain_name_joins_the_river(self, identity_db):
        mithi = _bodies(identity_db, "MITHI")[0]
        assert "Mithi Nallah" in mithi.aliases
        assert (
            identity_db.query(WaterBody).filter(WaterBody.name == "Mithi Nallah").count()
            == 0
        )

    def test_yamuna_is_one_river_across_states(self, identity_db):
        yamuna = _bodies(identity_db, "YAMUNA")
        assert len(yamuna) == 1
        assert yamuna[0].station_count == 3

    def test_spelling_variants_converge(self, identity_db):
        brahmaputra = _bodies(identity_db, "BRAHMAPUTRA")
        assert len(brahmaputra) == 1
        assert brahmaputra[0].name == "Brahmaputra River"
        assert "Brahamputra River" in brahmaputra[0].aliases
        assert _bodies(identity_db, "BRAHAMPUTRA") == []


class TestSameNameDifferentFeature:
    def test_same_lake_name_in_two_states_stays_two(self, identity_db):
        assert len(_bodies(identity_db, "RANI")) == 2

    def test_same_river_name_far_apart_stays_two(self, identity_db):
        amravati = _bodies(identity_db, "AMRAVATI")
        assert len(amravati) == 2


class TestDescriptorParsing:
    def test_descriptor_preserves_abbreviations(self):
        match = resolve("GODAVARI AT NASIK D/S GADGEBABA")
        assert sampling_descriptor("GODAVARI AT NASIK D/S GADGEBABA", match) == (
            "At Nasik D/S Gadgebaba"
        )

    def test_no_descriptor_when_the_label_is_only_the_name(self):
        assert resolve("ABBIGERE LAKE").position is None


# ---------------------------------------------------------------------------
# Cross-state river fragments (link_river_fragments)
# ---------------------------------------------------------------------------
def _fragment(db, source, name, slug, stations):
    body = WaterBody(
        slug=slug,
        name=name,
        normalized_name=name.upper(),
        water_type=WaterBodyType.RIVER,
        station_count=len(stations),
    )
    db.add(body)
    db.flush()
    for i, (lat, lon) in enumerate(stations):
        db.add(
            MonitoringStation(
                station_code=f"{slug}:{i}",
                name=f"{name} station {i}",
                slug=f"{slug}-{i}",
                source_id=source.id,
                water_body_id=body.id,
                latitude=lat,
                longitude=lon,
            )
        )
    db.commit()
    return body


class TestRiverFragmentLinking:
    """Stations are fixtures; positions are chosen for the distances only."""

    def _source(self, db):
        from app.models.water import DataSource

        src = DataSource(key="t", name="t", organisation="t")
        db.add(src)
        db.flush()
        return src

    def test_connected_fragments_become_one_river(self, db):
        from app.models.water_geo import WaterBodyGeometry
        from app.water.ingestion import link_river_fragments

        src = self._source(db)
        # ~100 km between the nearest stations across the state line, but the
        # far ends are 900 km apart: the centroid rule split these.
        a = _fragment(db, src, "Ganga River", "ganga-river", [(25.3, 83.0), (25.4, 81.0)])
        b = _fragment(
            db,
            src,
            "Ganga River (Bihar)",
            "ganga-river-bihar",
            [(25.5, 84.0), (25.4, 87.5)],
        )
        db.add(
            WaterBodyGeometry(
                water_body_id=b.id,
                geometry_type="LineString",
                geojson="{}",
                min_lat=0,
                min_lon=0,
                max_lat=0,
                max_lon=0,
                source="t",
                source_ids=[],
                retrieved_at=WHEN,
                confidence="high",
                match_method="t",
            )
        )
        db.commit()
        result = link_river_fragments(db)
        assert result["merged"] == 1
        rivers = db.scalars(
            select(WaterBody).where(WaterBody.water_type == "river")
        ).all()
        assert [r.slug for r in rivers] == ["ganga-river"]
        assert "Ganga River (Bihar)" in rivers[0].aliases
        assert (
            db.scalar(
                select(func.count(MonitoringStation.id)).where(
                    MonitoringStation.water_body_id == a.id
                )
            )
            == 4
        )
        # A geometry matched to one fragment does not describe the whole
        # merged river, so it must be re-matched -- but it is kept, and moved
        # to the survivor, rather than deleted. Deleting it took the Ganga and
        # its 134 stations off the map the moment an unrelated ingest ran a
        # reconcile, and nothing put it back until the geometry job next ran.
        # Incomplete is not the same as wrong.
        remaining = db.scalars(select(WaterBodyGeometry)).all()
        assert len(remaining) == 1
        assert remaining[0].water_body_id == a.id, "moved to the surviving body"
        assert rivers[0].geometry_status == "stale_after_merge", (
            "flagged for the next geometry pass, which treats it as missing"
        )

    def test_qualifier_dropped_when_whole_group_merges(self, db):
        from app.water.ingestion import link_river_fragments

        src = self._source(db)
        _fragment(db, src, "Yamuna River (Delhi)", "yamuna-river-delhi", [(28.6, 77.3)])
        _fragment(
            db, src, "Yamuna River (Uttar Pradesh)", "yamuna-river-up", [(27.5, 77.7)]
        )
        link_river_fragments(db)
        body = db.scalar(select(WaterBody))
        assert body.name == "Yamuna River"
        assert {"Yamuna River (Delhi)", "Yamuna River (Uttar Pradesh)"} & set(
            body.aliases
        )

    def test_distant_same_named_rivers_stay_separate(self, db):
        from app.water.ingestion import link_river_fragments

        src = self._source(db)
        _fragment(db, src, "Amravati River", "amravati-river", [(10.73, 77.52)])
        _fragment(
            db, src, "Amravati River (Gujarat)", "amravati-river-gj", [(21.6, 73.0)]
        )
        assert link_river_fragments(db)["merged"] == 0
        assert db.scalar(select(func.count(WaterBody.id))) == 2

    def test_main_river_takes_plain_name_distant_one_is_qualified(self, db):
        from app.models.water import State
        from app.water.ingestion import link_river_fragments

        src = self._source(db)
        ar = State(code="AR", name="Arunachal Pradesh", slug="arunachal-pradesh")
        db.add(ar)
        db.flush()
        far = _fragment(db, src, "Ganga River", "ganga-river", [(27.07, 93.61)])
        far.state_id = ar.id
        _fragment(
            db,
            src,
            "Ganga River (Bihar)",
            "ganga-river-bihar",
            [(25.5, 84.0), (25.4, 85.0)],
        )
        _fragment(
            db, src, "Ganga River (Uttar Pradesh)", "ganga-river-up", [(25.3, 83.0)]
        )
        db.commit()
        link_river_fragments(db)
        names = {b.slug: b.name for b in db.scalars(select(WaterBody))}
        # Slugs are kept; the connected river gets the plain name.
        assert names == {
            "ganga-river-bihar": "Ganga River",
            "ganga-river": "Ganga River (Arunachal Pradesh)",
        }


class TestTributaryAndSpelling:
    """Regressions found by running geometry QA over real CWC rows."""

    def test_station_named_for_the_tributary_resolves_to_it(self):
        """CWC rows carry both; "Purna at Gopalkheda" samples the Purna."""
        result = resolve("Purna at Gopalkheda", river="Tapi", tributary="Purna")
        assert result.name == "Purna River"
        assert result.method == "source_field"

    def test_main_river_still_wins_when_not_named_for_the_tributary(self):
        result = resolve("Tapi at Sarangkheda", river="Tapi", tributary="Purna")
        assert result.name == "Tapi River"

    def test_spelling_variants_of_sutlej_converge(self):
        from app.water.matching import canonical_core

        assert canonical_core("SATLUJ") == canonical_core("SUTLEJ")

    def test_fragment_linking_groups_spelling_variants(self, db):
        from app.models.water import DataSource
        from app.water.ingestion import link_river_fragments

        source = DataSource(key="t2", name="t", organisation="t")
        db.add(source)
        db.flush()
        _fragment(db, source, "Satluj River", "satluj-river", [(31.10, 76.50)])
        _fragment(db, source, "Sutlej River", "sutlej-river", [(31.15, 76.60)])
        assert link_river_fragments(db)["merged"] == 1

    def test_renaming_never_rewrites_the_identity_key(self, db):
        """Regression: qualifying a name changed normalized_name.

        ``normalized_name`` is the key every later match is made against.
        Deriving it from the display name turned "AMRAVATI" into
        "AMRAVATI RIVER", after which nothing matched the river again.
        """
        from app.models.water import DataSource, State
        from app.water.ingestion import link_river_fragments

        source = DataSource(key="t3", name="t", organisation="t")
        db.add(source)
        tn = State(code="TN", name="Tamil Nadu", slug="tamil-nadu")
        db.add(tn)
        db.flush()
        near = _fragment(db, source, "Amravati River", "amravati-river", [(10.73, 77.52)])
        near.normalized_name = "AMRAVATI"
        far = _fragment(db, source, "Amravati River", "amravati-2", [(21.60, 73.00)])
        far.normalized_name = "AMRAVATI"
        far.state_id = tn.id
        db.commit()

        link_river_fragments(db)
        bodies = db.query(WaterBody).filter(WaterBody.normalized_name == "AMRAVATI").all()
        assert len(bodies) == 2, "both keep the canonical key"
        assert {b.name for b in bodies} == {
            "Amravati River",
            "Amravati River (Tamil Nadu)",
        }


class TestConfluenceShorthand:
    """``A/c`` and ``B/c`` mark a position, not a water body.

    Both agencies label gauges by their confluences: "Krishna A/c With
    Tungabhadra" is the Krishna just after the Tungabhadra joins it. Reading
    the shorthand as part of the name produced 31 water bodies with one
    station each.
    """

    @pytest.mark.parametrize(
        ("label", "expected", "position"),
        [
            ("Krishna A/c With Tungabhadra", "Krishna", "A/C With Tungabhadra"),
            ("Mahanadi A/c With Tel", "Mahanadi", "A/C With Tel"),
            ("Kharoon River A/c Khapri Drain", "Kharoon River", "A/C Khapri Drain"),
            ("Tirthan B/c TO River Satluj", "Tirthan", "B/C To River Satluj"),
        ],
    )
    def test_the_name_stops_at_the_confluence_marker(self, label, expected, position):
        result = resolve(label)
        assert result.name == expected
        assert result.position == position

    def test_canonical_spelling_still_applies_after_the_cut(self):
        result = resolve("Satluj River B/c With River")
        assert result.name == "Sutlej River"
