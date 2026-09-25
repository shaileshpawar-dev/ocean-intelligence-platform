"""Tests for the water intelligence domain logic.

These are the water-side counterpart of the marine scientific-integrity
contract: they assert the properties that make the platform trustworthy
rather than merely functional. A failure here is a correctness bug.

The properties under test:

* a missing measurement never reads as zero, and never as compliance;
* dissolved oxygen is judged in the opposite direction to every pollutant;
* an observation too old for its source's cadence cannot produce a
  present-tense status;
* status is never a made-up score -- every band cites the parameters and
  limits that produced it;
* water-body identity is resolved deterministically, with the confidence of
  the method that produced it recorded;
* ingestion is idempotent and flags bad data rather than discarding it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.enums import QualityFlag, WaterBodyType, WaterStatus
from app.water.freshness import Cadence, Freshness, assess
from app.water.matching import (
    apply_propagation,
    haversine_km,
    is_plausible_merge,
    merge_key,
    normalise_name,
    propagate_types,
    resolve,
    slugify,
)
from app.water.parameters import BY_KEY, parse_value
from app.water.parameters import resolve as resolve_parameter
from app.water.reference_catalog import BY_CODE, EP_BATHING
from app.water.standards import (
    Compliance,
    DesignatedUse,
    SelectionBasis,
    compare,
    priority_band,
    select_reference,
    threshold_for,
)
from app.water.status import ClassificationRef, Measurement, evaluate, roll_up

NOW = datetime(2026, 9, 21, tzinfo=UTC)


def _recent(days: int = 3) -> datetime:
    """A timestamp recent enough to pass the freshness gate."""
    return NOW - timedelta(days=days)


# ---------------------------------------------------------------------------
class TestParameterRegistry:
    def test_resolves_published_headers_including_typos(self):
        # These are the exact column headers CPCB publishes, typo included.
        assert resolve_parameter("Amonia N (mgN/L)").key == "ammonia_n"
        assert resolve_parameter("Mercury(mg/L)").key == "mercury"
        assert resolve_parameter("Iron(mg/L)").key == "iron"
        assert resolve_parameter("Potential of Hydrogen (pH)").key == "ph"
        assert resolve_parameter("Biochemical Oxygen Demand (mg/L)").key == "bod"

    def test_unknown_column_returns_none_rather_than_guessing(self):
        assert resolve_parameter("Unobtainium (mg/L)") is None
        assert resolve_parameter("") is None

    def test_dissolved_oxygen_direction_is_inverted(self):
        assert BY_KEY["dissolved_oxygen"].higher_is_worse is False
        assert BY_KEY["bod"].higher_is_worse is True

    def test_two_sided_parameters_have_no_direction(self):
        assert BY_KEY["ph"].higher_is_worse is None


class TestValueParsing:
    @pytest.mark.parametrize("token", ["-", "", "NA", "n/a", "null", "None", "--"])
    def test_missing_tokens_never_become_zero(self, token):
        """The single most dangerous bug available: 0 BOD reads as pristine."""
        parsed = parse_value(BY_KEY["bod"], token)
        assert parsed.is_missing
        assert parsed.value is None
        assert parsed.value != 0

    def test_none_is_missing(self):
        assert parse_value(BY_KEY["bod"], None).is_missing

    def test_censored_value_keeps_number_and_flags_itself(self):
        parsed = parse_value(BY_KEY["lead"], "<0.01")
        assert parsed.value == 0.01
        assert "censored" in parsed.flags

    def test_unparseable_text_is_preserved_not_dropped(self):
        parsed = parse_value(BY_KEY["bod"], "not recorded")
        assert "unparseable" in parsed.flags
        assert parsed.raw == "not recorded"

    def test_qualitative_parameter_keeps_its_word(self):
        parsed = parse_value(BY_KEY["colour"], "Greenish")
        assert parsed.qualitative == "Greenish"
        assert parsed.value is None

    def test_conductivity_magnitude_decides_unit(self):
        """CPCB's header says mS/cm but publishes uS/cm magnitudes."""
        parsed = parse_value(BY_KEY["electrical_conductivity"], "1500")
        assert parsed.normalized_value == 1500.0
        assert parsed.unit == "uS/cm"


# ---------------------------------------------------------------------------
class TestStandards:
    def test_thresholds_carry_their_source(self):
        limit = threshold_for("bod", DesignatedUse.C)
        assert limit is not None
        assert limit.maximum == 3.0
        standard = BY_CODE["CPCB-DBU-C"]
        assert "CPCB" in standard.legal_basis
        assert standard.source_url

    def test_bathing_criteria_match_the_published_schedule(self):
        """Values as read from EP Rules 1986, item 93."""
        assert EP_BATHING.threshold("bod").maximum == 3.0
        assert EP_BATHING.threshold("dissolved_oxygen").minimum == 5.0
        ph = EP_BATHING.threshold("ph")
        assert (ph.minimum, ph.maximum) == (6.5, 8.5)
        fc = EP_BATHING.threshold("fecal_coliform")
        assert (fc.maximum, fc.desirable) == (2500, 500)

    def test_desirable_level_is_advisory_not_a_breach(self):
        result = compare("fecal_coliform", 1200.0, EP_BATHING)
        assert result.failed is False
        assert result.above_desirable is True
        assert compare("fecal_coliform", 11000.0, EP_BATHING).failed is True

    def test_missing_value_is_not_compliance(self):
        result = compare("bod", None, DesignatedUse.C)
        assert result.compliance is Compliance.NOT_MEASURED
        assert result.failed is False
        assert "not measured" in result.explain().lower()

    def test_absent_standard_is_not_compliance(self):
        """Class D sets no BOD limit; that is not a pass."""
        result = compare("bod", 500.0, DesignatedUse.D)
        assert result.compliance is Compliance.NO_STANDARD
        assert result.failed is False

    def test_no_reference_is_not_compliance(self):
        result = compare("bod", 40.0, None)
        assert result.compliance is Compliance.NO_REFERENCE
        assert result.failed is False

    def test_exceedance_is_detected_with_factor(self):
        result = compare("bod", 30.0, DesignatedUse.C)
        assert result.compliance is Compliance.EXCEEDS
        assert result.failed
        assert result.exceedance_factor == pytest.approx(10.0)

    def test_dissolved_oxygen_fails_when_too_low(self):
        result = compare("dissolved_oxygen", 1.0, DesignatedUse.C)
        assert result.compliance is Compliance.BELOW
        assert result.failed

    def test_dissolved_oxygen_high_is_not_a_failure(self):
        assert compare("dissolved_oxygen", 9.0, DesignatedUse.C).failed is False

    def test_class_changes_the_verdict(self):
        """Same water, different designated use, legitimately different answer."""
        assert compare("bod", 2.5, DesignatedUse.A).failed is True
        assert compare("bod", 2.5, DesignatedUse.C).failed is False

    @pytest.mark.parametrize(
        ("bod", "band"),
        [(40.0, "I"), (25.0, "II"), (15.0, "III"), (8.0, "IV"), (4.0, "V")],
    )
    def test_cpcb_priority_bands(self, bod, band):
        assert priority_band(bod)[0] == band

    def test_bod_at_or_below_threshold_is_not_a_band(self):
        assert priority_band(3.0) is None
        assert priority_band(None) is None


class TestReferenceSelection:
    """Phase 2: no standard is applied by default."""

    def test_rivers_get_the_national_assessment_reference(self):
        selection = select_reference("river")
        assert selection.standard is EP_BATHING
        assert selection.basis is SelectionBasis.NATIONAL_ASSESSMENT_CATEGORY
        assert "polluted river stretches" in selection.reason

    @pytest.mark.parametrize(
        "water_type", ["lake", "pond", "reservoir", "creek", "canal", "drain", "other"]
    )
    def test_no_hidden_class_c_default(self, water_type):
        selection = select_reference(water_type)
        assert selection.standard is None
        assert selection.basis is SelectionBasis.NONE
        assert selection.reason

    def test_groundwater_reason_names_the_missing_standard(self):
        assert "IS 10500" in select_reference("groundwater").reason

    def test_recorded_designated_use_wins_over_national_category(self):
        selection = select_reference("river", designated_use="A")
        assert selection.standard.code == "CPCB-DBU-A"
        assert selection.basis is SelectionBasis.WATER_BODY_DESIGNATED_USE

    def test_explicit_choice_wins_over_everything(self):
        selection = select_reference("lake", explicit="B", designated_use="A")
        assert selection.standard.code == "CPCB-DBU-B"
        assert selection.basis is SelectionBasis.USER_SELECTED

    def test_unknown_explicit_code_falls_back_to_selection(self):
        assert select_reference("lake", explicit="NOT-A-STANDARD").standard is None


# ---------------------------------------------------------------------------
class TestFreshness:
    def test_never_observed_is_distinct_from_stale(self):
        assert assess(None, Cadence.MONTHLY, now=NOW).freshness is (
            Freshness.NEVER_OBSERVED
        )

    def test_recent_monthly_observation_is_recent(self):
        result = assess(NOW - timedelta(days=5), Cadence.MONTHLY, now=NOW)
        assert result.freshness is Freshness.RECENT
        assert result.describes_present_state

    def test_cadence_changes_the_verdict_for_the_same_age(self):
        """A single global staleness rule would get one of these wrong.

        Ten days is unremarkable for a monthly programme and overdue for a
        daily gauge; a flat "stale after 7 days" rule would flag the first
        and a flat "stale after 30" would miss the second.
        """
        age = NOW - timedelta(days=10)
        assert assess(age, Cadence.MONTHLY, now=NOW).freshness is Freshness.RECENT
        assert (
            assess(age, Cadence.DAILY, now=NOW).freshness is Freshness.OLDER_THAN_CADENCE
        )
        # Far enough past a daily cadence to stop describing the present.
        assert (
            assess(NOW - timedelta(days=40), Cadence.DAILY, now=NOW).freshness
            is Freshness.NO_RECENT_DATA
        )

    def test_years_old_cannot_describe_the_present(self):
        result = assess(datetime(2021, 12, 2, tzinfo=UTC), Cadence.MONTHLY, now=NOW)
        assert result.freshness is Freshness.NO_RECENT_DATA
        assert result.describes_present_state is False

    def test_summary_never_claims_current(self):
        summary = assess(NOW - timedelta(days=5), Cadence.MONTHLY, now=NOW).summary()
        assert "latest available" in summary.lower()
        assert "current" not in summary.lower()

    def test_future_dates_do_not_produce_negative_age(self):
        result = assess(NOW + timedelta(days=30), Cadence.MONTHLY, now=NOW)
        assert result.age_days == 0.0


# ---------------------------------------------------------------------------
RIVER = select_reference("river")
NO_REF = select_reference("lake")
CLASS_C = select_reference("lake", explicit="C")


class TestStatusEngine:
    def test_no_observations_is_not_clean(self):
        result = evaluate([], reference=RIVER, now=NOW)
        assert result.status is WaterStatus.NO_RECENT_DATA
        assert "not evidence that the water is clean" in " ".join(result.reasons)

    def test_stale_data_cannot_produce_present_tense_status(self):
        """Real Mithi values from 2018 must not describe the river today."""
        old = datetime(2018, 12, 4, tzinfo=UTC)
        result = evaluate(
            [Measurement("bod", 40.0, old), Measurement("fecal_coliform", 920.0, old)],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.NO_RECENT_DATA
        assert "cannot be established" in " ".join(result.reasons)
        # The comparison is still computed so the reader can see what it showed.
        assert any(c.failed for c in result.comparisons)

    def test_one_high_reading_is_never_a_polluted_stretch(self):
        """Phase 2: that label comes only from a source classification."""
        result = evaluate(
            [Measurement("bod", 40.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.HIGH_CONCERN
        assert result.status is not WaterStatus.POLLUTED_STRETCH

    def test_official_classification_produces_polluted_stretch(self):
        stretch = ClassificationRef(
            source="CPCB",
            classification_type="polluted_river_stretch",
            assessment_year=2025,
            priority="IV",
            stretch_name="Test stretch",
            source_reference="test",
        )
        result = evaluate(
            [Measurement("bod", 8.0, _recent())],
            reference=RIVER,
            classifications=[stretch],
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.POLLUTED_STRETCH
        payload = result.to_dict()
        assert (
            payload["source_classifications"][0]["evidence_type"]
            == "SOURCE_CLASSIFICATION"
        )

    def test_no_reference_means_no_judgement(self):
        result = evaluate(
            [Measurement("bod", 40.0, _recent())],
            reference=NO_REF,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.NO_APPLICABLE_REFERENCE
        assert result.failing == []
        assert "Reference comparison unavailable" in result.reasons[0]
        # The measurement is still reported.
        assert result.to_dict()["measurements"][0]["value"] == 40.0

    def test_unmeasured_governed_parameters_are_insufficient_not_clean(self):
        result = evaluate(
            [Measurement("calcium", 40.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.INSUFFICIENT_DATA
        assert "not a finding that the water is within limits" in " ".join(result.reasons)

    def test_clean_water_is_within_reference(self):
        observed = _recent()
        result = evaluate(
            [
                Measurement("bod", 1.0, observed),
                Measurement("dissolved_oxygen", 7.5, observed),
                Measurement("ph", 7.2, observed),
            ],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.WITHIN_REFERENCE

    def test_low_oxygen_alone_is_flagged(self):
        result = evaluate(
            [Measurement("dissolved_oxygen", 4.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.ELEVATED
        assert result.failing[0].parameter_key == "dissolved_oxygen"

    def test_severe_single_breach_escalates(self):
        result = evaluate(
            [Measurement("fecal_coliform", 50_000.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert result.status is WaterStatus.HIGH_CONCERN

    def test_layers_are_separate_and_unscored(self):
        """No opaque number, and each layer carries its own evidence type."""
        result = evaluate(
            [Measurement("bod", 12.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        payload = result.to_dict()
        assert "score" not in payload
        assert payload["evidence_type"] == "DERIVED_STATUS"
        assert payload["measurements"][0]["evidence_type"] == "MEASURED"
        assert payload["comparisons"][0]["evidence_type"] == "REFERENCE_COMPARISON"
        assert payload["reference"]["basis"] == "national_assessment_category"
        assert payload["failing_parameters"][0]["standard_url"]

    def test_reasons_carry_the_observation_date(self):
        result = evaluate(
            [Measurement("bod", 12.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert any("Observations used" in r for r in result.reasons)

    def test_missing_parameters_are_named(self):
        result = evaluate(
            [Measurement("bod", 1.0, _recent())],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert "Dissolved oxygen" in result.missing_parameters

    def test_rollup_takes_the_worst_not_the_average(self):
        observed = _recent()
        clean = evaluate(
            [Measurement("bod", 1.0, observed)],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        dirty = evaluate(
            [Measurement("bod", 40.0, observed)],
            reference=RIVER,
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        assert roll_up([clean, dirty]) is WaterStatus.HIGH_CONCERN

    def test_selected_standard_is_reported_with_the_verdict(self):
        result = evaluate(
            [Measurement("bod", 2.5, _recent())],
            reference=select_reference("lake", explicit="A"),
            cadence=Cadence.MONTHLY,
            now=NOW,
        )
        payload = result.to_dict()
        assert payload["reference"]["standard_code"] == "CPCB-DBU-A"
        assert payload["reference"]["basis"] == "user_selected"
        assert result.status is WaterStatus.ELEVATED


# ---------------------------------------------------------------------------
class TestWaterBodyMatching:
    @pytest.mark.parametrize(
        ("station", "name", "wtype"),
        [
            ("MITHI RIVER MAHIM BANDRA MUMBAI", "Mithi River", WaterBodyType.RIVER),
            ("RIVER COOUM AT AMANJIKARAI", "Cooum River", WaterBodyType.RIVER),
            (
                "RIVER GANGA AT MADHYA GANGA BARRAGE BIJNOR",
                "Ganga River",
                WaterBodyType.RIVER,
            ),
            ("ABBIGERE LAKE", "Abbigere Lake", WaterBodyType.LAKE),
            ("DEEPAR BEEL ASSAM", "Deepar Beel", WaterBodyType.LAKE),
            ("JOLADAKATTE TANK", "Joladakatte Tank", WaterBodyType.POND),
            ("ARNALA SEA ARNALA VASAI THANE", "Arnala Sea", WaterBodyType.COASTAL),
        ],
    )
    def test_real_station_names_resolve(self, station, name, wtype):
        result = resolve(station)
        assert result.name == name
        assert result.water_type is wtype

    def test_sampling_position_never_leaks_into_the_name(self):
        """The bug that made 'Ganga at Madhya Ganga Barrage Bijnor' a river."""
        for station in (
            "GODAVARI AT NASIK D/S GADGEBABA MAHARAJ NAGAR NASHIK",
            "KRISHNA D/S OF ISLAMPUR WALWA SANGLI",
            "BHADRA AT D/S OF KIOCL ROAD BRIDGE NEAR HOLEHUNNUR",
        ):
            name = resolve(station).name.lower()
            for marker in (" at ", " d/s", " u/s", "near", "bridge"):
                assert marker not in name

    @pytest.mark.parametrize(
        "station",
        [
            "GROUND WATER AT DIGBOI TINSUKIA DISTT. ASSAM",
            "BORE WELL AT WAHEGAON NEAR ZILLA PARISHAD SCHOOL",
            "WELL AT QUTAB GARH DELHI",
            "PATAN BOREWELL",
        ],
    )
    def test_groundwater_is_not_typed_as_surface_water(self, station):
        assert resolve(station).water_type is WaterBodyType.GROUNDWATER

    def test_overhead_service_tank_is_not_a_lake(self):
        result = resolve("OVER HEAD TANK AT TIRUR VILLAGE TIRUVALLUR")
        assert result.water_type is not WaterBodyType.POND
        assert result.water_type is WaterBodyType.OTHER

    def test_coastal_stations_are_distinguished_not_merged(self):
        """'SEA WATER AT X' must not collapse every beach into one body."""
        juhu = resolve("SEA WATER AT JUHU BEACH JUHUGAON SANTACRUZ MUMBAI")
        worli = resolve("SEA WATER AT WORLI SEA FACE WORLI MUMBAI")
        assert juhu.water_type is WaterBodyType.COASTAL
        assert worli.water_type is WaterBodyType.COASTAL
        assert juhu.normalized_name != worli.normalized_name

    def test_source_field_beats_name_parsing(self):
        result = resolve("SOME UNHELPFUL STATION LABEL", river="Yamuna")
        assert result.method == "source_field"
        assert result.confidence == 1.0
        assert result.name == "Yamuna River"

    def test_unidentifiable_names_say_so(self):
        result = resolve("ERODE-2")
        assert result.method == "unclassified"
        assert result.water_type is WaterBodyType.OTHER
        assert result.confidence < 0.5

    def test_type_is_propagated_from_the_corpus_not_hardcoded(self):
        explicit = resolve("BRAHAMPUTRA RIVER AT BOGIBEEL BRIDGE DIBRUGARH")
        bare = resolve("BRAHAMPUTRA AT GUWAHATI")
        assert bare.water_type is WaterBodyType.OTHER

        learned = propagate_types([explicit, bare])
        upgraded = apply_propagation(bare, learned)
        assert upgraded.water_type is WaterBodyType.RIVER
        assert upgraded.method == "type_propagated"
        assert upgraded.confidence < explicit.confidence

    def test_conflicting_types_are_not_resolved_by_vote(self):
        a = resolve("SURYA RIVER AT PLACE")
        b = resolve("SURYA LAKE")
        learned = propagate_types([a, b])
        assert a.normalized_name not in learned

    def test_distance_guard_separates_same_named_features(self):
        # Amravati in Tamil Nadu vs Gujarat: same name, ~1200 km apart.
        assert is_plausible_merge(10.7, 77.5, 21.6, 73.0) is False
        assert is_plausible_merge(19.05, 72.84, 19.10, 72.90) is True

    def test_missing_coordinates_do_not_block_a_merge(self):
        assert is_plausible_merge(None, None, 19.0, 72.0) is True

    def test_rivers_key_nationally_lakes_key_per_state(self):
        river = resolve("KRISHNA RIVER AT SANGLI")
        lake = resolve("POWAI LAKE")
        assert merge_key(river, "MH")[2] == ""
        assert merge_key(lake, "MH")[2] == "MH"

    def test_normalisation_and_slugs(self):
        assert normalise_name("Mithi  River!") == "MITHI RIVER"
        assert slugify("Mithi River") == "mithi-river"
        assert slugify("") == "unnamed"

    def test_haversine_is_accurate(self):
        # Mumbai to Pune, ~120 km.
        assert 115 < haversine_km(19.076, 72.877, 18.520, 73.856) < 130


# ---------------------------------------------------------------------------
class TestIngestionValidation:
    def test_implausible_value_is_flagged_not_dropped(self):
        from app.water.ingestion import _validate
        from app.water.providers import ObservationRow

        row = ObservationRow(
            station_name="X",
            parameter_key="ph",
            observed_at=NOW,
            value=780.0,
        )
        flag, notes = _validate(row)
        assert flag is QualityFlag.SUSPECT
        assert any("outside_plausible_range" in n for n in notes)

    def test_value_with_no_number_is_invalid(self):
        from app.water.ingestion import _validate
        from app.water.providers import ObservationRow

        row = ObservationRow(station_name="X", parameter_key="bod", observed_at=NOW)
        flag, _ = _validate(row)
        assert flag is QualityFlag.INVALID

    def test_plausible_value_passes_clean(self):
        from app.water.ingestion import _validate
        from app.water.providers import ObservationRow

        row = ObservationRow(
            station_name="X", parameter_key="bod", observed_at=NOW, value=4.2
        )
        flag, notes = _validate(row)
        assert flag is QualityFlag.OK
        assert notes == []

    def test_naive_and_aware_datetimes_compare_equal(self):
        """The bug that made re-ingestion crash on the unique constraint."""
        from app.water.ingestion import _as_utc

        naive = datetime(2021, 12, 2, 8, 30)
        aware = datetime(2021, 12, 2, 8, 30, tzinfo=UTC)
        assert _as_utc(naive) == _as_utc(aware)
        assert _as_utc(None) is None


class TestLeadingArticle:
    def test_the_is_not_a_river_name(self):
        """Regression: THE RIVER ASHWANI AT ... became a river called "The"."""
        from app.water.matching import resolve

        r = resolve(
            "THE RIVER ASHWANI AT VILLAGE SADHUPIL TEHSIL KANDAGHAT DISTRICT SOLAN."
        )
        assert r.name == "Ashwani River"
        assert str(r.water_type) == "river"


class TestUnitNormalisation:
    """Units are converted only when the conversion is exact."""

    def _parse(self, column: str, raw: str):
        from app.water.parameters import parse_value, resolve

        parameter = resolve(column)
        assert parameter is not None, column
        return parameter, parse_value(parameter, raw, source_unit=column)

    def test_same_unit_passes_through(self):
        _, v = self._parse("Biochemical Oxygen Demand (mg/L)", "3.2")
        assert (v.value, v.normalized_value, v.unit) == (3.2, 3.2, "mg/L")
        assert v.flags == []

    def test_microgram_converts_to_milligram(self):
        from app.water.parameters import BY_KEY, normalise_value

        value, unit = normalise_value(BY_KEY["bod"], 2000.0, "ug/L")
        assert (value, unit) == (2.0, "mg/L")

    def test_millisiemens_converts_when_plausible(self):
        _, v = self._parse("Electric Conductivity (mS/cm)", "0.4")
        assert v.normalized_value == 400.0
        assert v.unit == "uS/cm"
        assert v.flags == []

    def test_mislabelled_conductivity_is_not_inflated_and_is_flagged(self):
        """Both CPCB and CWC label uS/cm values as mS/cm.

        309 mS/cm would be six times seawater; converting on the header
        would multiply every reading by a thousand.
        """
        _, v = self._parse("Electric Conductivity (mS/cm)", "309")
        assert v.normalized_value == 309.0
        assert "unit_assumed_us_cm" in v.flags

    def test_unknown_unit_is_not_converted(self):
        from app.water.parameters import BY_KEY, normalise_value

        value, unit = normalise_value(BY_KEY["bod"], 5.0, "grains/gallon")
        assert (value, unit) == (None, None)

    def test_dimensionless_parameters_are_left_alone(self):
        _, v = self._parse("pH", "7.4")
        assert v.value == 7.4 and v.unit is None

    def test_missing_tokens_never_become_zero(self):
        for token in ("-", "", "NA", "n/a", "nil"):
            _, value = self._parse("Turbidity (NTU)", token)
            assert value.is_missing, token
            assert value.value is None
