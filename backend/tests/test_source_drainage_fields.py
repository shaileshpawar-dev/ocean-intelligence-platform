"""The source's River / Basin / Tributary columns are not all the same thing.

Geometry QA on the real CWC data found 511 stations more than 25 km from the
water body they had been assigned to -- every Sikkim station sat on the
Brahmaputra mainstem, up to 264 km from the Teesta it actually samples. The
cause was reading the ``River`` column as the water body. In 72% of the rows
sampled (100% for Uttar Pradesh) that column simply repeats ``Basin``, and
the watercourse is in ``Tributary``.

The rule these tests pin down:

* ``River`` != ``Basin`` -- the river column names a watercourse (Odisha:
  basin "Brahmani and Baitarni", river "Baitarani").
* ``River`` == ``Basin`` -- it is a basin label. An empty ``Tributary``
  ("-") then means the basin's main river; a populated one names the
  sub-basin, recorded at lower confidence because a sub-basin can still be
  coarser than the stream sampled.
* The more specific name wins.
* A lake, tank or well named in the station label is that water body,
  whatever basin it drains to.

Every case below is taken from rows published on the portal.
"""

from __future__ import annotations

import pytest
from app.models.water import WaterBodyType
from app.water.matching import CONFIDENCE, resolve


class TestBasinLabelIsNotAWaterBody:
    """``River`` repeating ``Basin`` must not become the water body."""

    def test_sikkim_station_resolves_to_the_tributary_not_the_basin(self):
        # River=Brahmaputra, Basin=Brahmaputra, Tributary=Teesta for every
        # Sikkim row. "Bakcha" names no water body itself.
        match = resolve(
            "Bakcha", river="Brahmaputra", tributary="Teesta", basin="Brahmaputra"
        )
        assert match.name == "Teesta River"
        assert match.method == "source_sub_basin"
        assert match.confidence == CONFIDENCE["source_sub_basin"]

    def test_sub_basin_confidence_is_below_a_named_river(self):
        assert CONFIDENCE["source_sub_basin"] < CONFIDENCE["source_field"]

    def test_madhya_pradesh_ganga_basin_station_resolves_to_the_sub_basin(self):
        match = resolve("Ujjain", river="Ganga", tributary="Yamuna", basin="Ganga")
        assert match.name == "Yamuna River"
        assert match.method == "source_sub_basin"

    @pytest.mark.parametrize("tributary", ["-", "", "--", "NA", "n/a", "."])
    def test_empty_tributary_means_the_basin_main_river(self, tributary):
        # Narmada basin, no tributary: the station is on the Narmada.
        match = resolve(
            "Hoshangabad", river="Narmada", tributary=tributary, basin="Narmada"
        )
        assert match.name == "Narmada River"
        assert match.method == "source_field"
        assert match.confidence == CONFIDENCE["source_field"]

    def test_tributary_repeating_the_river_still_means_the_main_river(self):
        match = resolve("Sandia", river="Narmada", tributary="Narmada", basin="Narmada")
        assert match.name == "Narmada River"
        assert match.method == "source_field"


class TestRiverColumnTrustedWhenItDiffersFromBasin:
    """Odisha publishes a real river name against a grouped basin."""

    def test_river_wins_when_it_is_not_the_basin(self):
        match = resolve(
            "Akhuapada",
            river="Baitarani",
            tributary="-",
            basin="Brahmani and Baitarni",
        )
        assert match.name == "Baitarani River"
        assert match.method == "source_field"
        assert match.confidence == CONFIDENCE["source_field"]

    def test_a_populated_tributary_is_more_specific_than_its_river(self):
        match = resolve(
            "Champua",
            river="Baitarani",
            tributary="Ararai",
            basin="Brahmani and Baitarni",
        )
        assert match.name == "Ararai River"
        assert match.method == "source_field"

    def test_tributary_wins_even_when_the_label_does_not_name_it(self):
        # The Phase 2 fix only preferred the tributary when the station name
        # contained it, which left every unnamed station on the main river.
        match = resolve("Gopalkheda", river="Tapi", tributary="Purna", basin="Tapi")
        assert match.name == "Purna River"


class TestTheLabelSettlesItWhenItNamesAColumn:
    """A station that says which watercourse it stands on is believed."""

    def test_label_naming_the_main_river_beats_the_sub_basin_column(self):
        match = resolve(
            "Ganga at Patna", river="Ganga", tributary="Yamuna", basin="Ganga"
        )
        assert match.name == "Ganga River"
        assert match.method == "source_field"

    def test_label_naming_the_tributary_beats_the_river(self):
        match = resolve(
            "Purna at Gopalkheda", river="Tapi", tributary="Purna", basin="Tapi"
        )
        assert match.name == "Purna River"
        assert match.method == "source_field"

    def test_label_naming_the_river_beats_the_tributary(self):
        match = resolve(
            "Tapi at Sarangkheda", river="Tapi", tributary="Purna", basin="Tapi"
        )
        assert match.name == "Tapi River"


class TestStillWaterAndGroundwaterOutrankDrainage:
    """A lake in a basin is not the basin's river."""

    def test_lake_in_the_brahmaputra_basin_stays_a_lake(self):
        match = resolve(
            "Gurudongmar Lake",
            river="Brahmaputra",
            tributary="Teesta",
            basin="Brahmaputra",
        )
        assert match.name == "Gurudongmar Lake"
        assert match.water_type is WaterBodyType.LAKE

    def test_lake_in_the_godavari_basin_stays_a_lake(self):
        match = resolve(
            "Koradi Lake", river="Godavari", tributary="Pranhita", basin="Godavari"
        )
        assert match.water_type is WaterBodyType.LAKE

    def test_groundwater_is_not_the_river_of_its_basin(self):
        match = resolve(
            "GROUND WATER AT VARANASI", river="Ganga", tributary="Yamuna", basin="Ganga"
        )
        assert match.water_type is WaterBodyType.GROUNDWATER

    def test_a_river_named_in_the_label_does_not_override_the_source(self):
        # Both agree it is a river, so the source field is still preferred:
        # it is the cleaner name.
        match = resolve(
            "NARMADA RIVER AT HOSHANGABAD",
            river="Narmada",
            tributary="-",
            basin="Narmada",
        )
        assert match.name == "Narmada River"
        assert match.water_type is WaterBodyType.RIVER


class TestSubBasinLabelsAreTidied:
    """The sub-basin column carries reach numbering, not river names."""

    def test_numbered_reach_and_state_suffix_are_stripped(self):
        match = resolve(
            "Ambari", river="Ganga", tributary="Bhagirathi-II (WB)*", basin="Ganga"
        )
        assert match.name == "Bhagirathi River"
        assert match.normalized_name == "BHAGIRATHI"

    def test_the_published_spelling_is_kept_as_an_alias(self):
        match = resolve(
            "Ambari", river="Ganga", tributary="Bhagirathi-II (WB)*", basin="Ganga"
        )
        assert "Bhagirathi-II (WB)*" in match.aliases

    def test_an_en_dashed_reach_number_is_also_stripped(self):
        match = resolve("X", river="Ganga", tributary="Yamuna – II", basin="Ganga")
        assert match.name == "Yamuna River"


class TestCpcbRowsAreUnaffected:
    """CPCB leaves all three columns empty; identity comes from the label."""

    def test_station_name_parse_still_applies(self):
        match = resolve("MITHI RIVER MAHIM BANDRA MUMBAI")
        assert match.name == "Mithi River"
        assert match.method == "station_name_parse"

    def test_blank_columns_are_ignored(self):
        # No keyword in the label, so the name is bare here and the river type
        # arrives from batch propagation, exactly as before this change.
        match = resolve("GODAVARI AT NASIK D/S", river="", tributary="-", basin="   ")
        assert match.name == "Godavari"
        assert match.method == "unclassified"
        assert match.position == "At Nasik D/S"
