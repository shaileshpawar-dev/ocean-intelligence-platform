"""GFW activity: aggregate only, and zero is an answer.

Two things pinned here.

**No vessel identity.** This platform associates vessels with SAR candidates
as ``SOURCE_SUSPECT`` at scores up to 0.97, and its candidates are research
benchmark patches -- nobody spilled anything. A real MMSI in that row would
name an identifiable ship as the source of an event that did not occur. So
the GFW payload carries flags and counts and no identifiers, and a test says
so rather than a convention holding.

**Zero is a finding.** "GFW answered and saw no effort here" and "we could
not ask" are different states, and collapsing them would turn an unprocessed
week of AIS into empty ocean.

Nothing here calls Global Fishing Watch.
"""

from __future__ import annotations

from datetime import date

from app.vision.gfw_client import (
    ATTRIBUTION,
    ATTRIBUTION_URL,
    EVIDENCE_LEVEL,
    GFWClient,
    RegionActivity,
)

#: Shaped like a real 4wings response, including the resolved dataset key.
PAYLOAD = {
    "entries": [
        {
            "public-global-fishing-effort:v5.0": [
                {"flag": "IND", "hours": 120.5, "lat": 21.4, "lon": 68.1, "vesselIDs": 7},
                {"flag": "IND", "hours": 80.0, "lat": 21.5, "lon": 68.2, "vesselIDs": 4},
                {"flag": "LKA", "hours": 23.5, "lat": 21.6, "lon": 68.3, "vesselIDs": 2},
            ]
        }
    ]
}


class TestParsingAReport:
    """Rows are summed per flag; the dataset key is read, not assumed."""

    @staticmethod
    def _parse(payload):
        return GFWClient._parse(
            "gulf_of_kutch_w", date(2026, 9, 30), date(2026, 11, 14), payload
        )

    def test_hours_are_summed_across_grid_cells(self):
        activity = self._parse(PAYLOAD)

        assert activity.total_hours == 224.0
        assert activity.hours_by_flag["IND"] == 200.5
        assert activity.vessel_count == 13
        assert activity.grid_cells == 3

    def test_the_resolved_dataset_key_is_read_from_the_response(self):
        """The request asks for ':latest' and the response answers with a
        concrete ':v5.0'. Matching on the requested name would drop every
        row the next time GFW bumps a version."""
        renamed = {"entries": [{"public-global-fishing-effort:v9.9": PAYLOAD["entries"][0]["public-global-fishing-effort:v5.0"]}]}

        assert self._parse(renamed).total_hours == 224.0

    def test_an_empty_report_is_zero_not_an_error(self):
        """A quiet region is a finding, and must survive as one."""
        activity = self._parse({"entries": []})

        assert activity.total_hours == 0.0
        assert activity.vessel_count == 0
        assert activity.grid_cells == 0

    def test_flags_come_back_heaviest_first(self):
        assert [flag for flag, _ in self._parse(PAYLOAD).top_flags] == ["IND", "LKA"]


class TestNoVesselIdentity:
    """The limit that keeps a real ship from being named a suspect."""

    @staticmethod
    def _payload() -> dict:
        return RegionActivity(
            cell_code="arabian_sea_z4",
            window_from="2026-09-30",
            window_to="2026-11-14",
            total_hours=15792.3,
            vessel_count=1613,
            grid_cells=410,
            hours_by_flag={"CHN": 9844.0, "IRN": 4801.0},
        ).to_dict()

    def test_the_payload_carries_no_vessel_identifiers(self):
        """Counts and flag states only -- never an MMSI, IMO, name or
        callsign. A flag is a country, not a ship."""
        blob = str(self._payload()).lower()

        for identifier in ("mmsi", "imo", "callsign", "shipname", "vessel_id"):
            assert identifier not in blob, f"{identifier} leaked into the payload"

    def test_flags_are_country_codes_not_vessels(self):
        flags = {entry["flag"] for entry in self._payload()["top_flags"]}

        assert flags == {"CHN", "IRN"}
        assert all(len(flag) == 3 for flag in flags)

    def test_the_payload_states_why_no_identity_is_attached(self):
        note = self._payload()["note"].lower()

        assert "aggregate" in note
        assert "identity" in note


class TestAttribution:
    """GFW asks to be credited wherever its data appears."""

    def test_every_reading_carries_the_required_credit(self):
        payload = TestNoVesselIdentity._payload()

        assert payload["attribution"] == ATTRIBUTION
        assert ATTRIBUTION == "Powered by Global Fishing Watch"
        assert payload["attribution_url"] == ATTRIBUTION_URL
        assert "globalfishingwatch.org" in ATTRIBUTION_URL

    def test_apparent_effort_is_inferred_not_observed(self):
        """AIS transmissions are recorded; the *fishing* is a model's
        inference from how the vessel moved. GFW calls it apparent."""
        assert EVIDENCE_LEVEL == "INFERRED"
        assert TestNoVesselIdentity._payload()["evidence_level"] == "INFERRED"
