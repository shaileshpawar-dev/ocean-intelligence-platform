"""Provider cards: derived from what each source produced, never configured.

The failure this guards is a card that says "Live" because someone wrote
"Live" in a config file. Every state here has to come from evidence — rows
in a table, files in a cache, a timestamp on a cached response — so that a
source which quietly stops producing is visible rather than still green.

The second thing pinned is the four-state vocabulary. "Sync paused" and
"Unavailable" are different claims, and the health CLI has to use the same
words as the page or a reader cannot tell which to believe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.services.provider_status import ProviderCard, _age_state, external_providers

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class TestStateComesFromAge:
    """Live while producing, stale once its data outruns its cadence."""

    def test_a_recent_fetch_is_live(self):
        state, detail = _age_state(NOW - timedelta(hours=3), 1, NOW)

        assert state == "live"
        assert "hours ago" in detail

    def test_data_past_three_cadences_is_stale(self):
        state, detail = _age_state(NOW - timedelta(days=40), 7, NOW)

        assert state == "stale"
        assert "past this source's expected cadence" in detail

    def test_a_source_never_fetched_is_unavailable(self):
        """Not "live with zero records", which is how a source that has
        never run once manages to look healthy."""
        state, detail = _age_state(None, 7, NOW)

        assert state == "unavailable"
        assert "Never fetched" in detail

    def test_cadence_is_respected_per_source(self):
        """The same age means different things to different sources.

        Staleness is three times the source's own expected cadence, so ten
        days is unremarkable for a satellite that revisits fortnightly and
        well past due for a daily fetch.
        """
        ten_days = NOW - timedelta(days=10)

        assert _age_state(ten_days, 14, NOW)[0] == "live"
        assert _age_state(ten_days, 1, NOW)[0] == "stale"


class TestTheVocabulary:
    """Four states, and the one that is most often got wrong."""

    @staticmethod
    def _card(state: str) -> ProviderCard:
        return ProviderCard(
            key="x",
            name="X",
            organisation="X",
            what_it_feeds="x",
            expected_cadence="daily",
            attribution="x",
            state=state,
            detail="x",
            records_held=0,
        )

    @pytest.mark.parametrize(
        ("state", "label", "tone"),
        [
            ("live", "Live", "ok"),
            ("stale", "Stale", "warn"),
            ("sync_paused", "Sync paused", "warn"),
            ("unavailable", "Unavailable", "bad"),
        ],
    )
    def test_each_state_has_its_own_label_and_tone(self, state, label, tone):
        card = self._card(state)

        assert card.label == label
        assert card.tone == tone

    def test_a_pause_is_amber_not_red(self):
        """A server that answers and refuses is not an outage, and colouring
        it as one sends somebody hunting a fault that is not there."""
        assert self._card("sync_paused").tone == "warn"
        assert self._card("unavailable").tone == "bad"


class TestEverySourceIsListed:
    """A page headed "where the numbers come from" must not omit sources."""

    def test_all_six_external_services_appear(self, db):
        keys = {card["key"] for card in external_providers(db, NOW)}

        assert keys == {
            "sentinel2",
            "sentinel1",
            "cmems",
            "open_meteo",
            "gfw",
            "gemini",
        }

    def test_each_card_says_what_it_feeds_and_credits_its_source(self, db):
        for card in external_providers(db, NOW):
            assert card["what_it_feeds"], card["key"]
            assert card["attribution"], card["key"]
            assert card["expected_cadence"], card["key"]

    def test_an_empty_deployment_reports_unavailable_not_live(self, db):
        """With no data fetched, every data-backed card must say so."""
        cards = {c["key"]: c for c in external_providers(db, NOW)}

        for key in ("sentinel2", "sentinel1"):
            assert cards[key]["status"]["state"] == "unavailable", key
            assert cards[key]["status"]["records_held"] == 0

    def test_gfw_card_states_the_identity_limit(self, db):
        card = next(c for c in external_providers(db, NOW) if c["key"] == "gfw")

        assert "Aggregate" in card["what_it_feeds"] or "aggregate" in (
            card["status"]["detail"]
        )

    def test_the_gemini_card_is_not_called_evidence(self, db):
        """Prose over computed values is not a data source, and the card
        should not let it read as one."""
        card = next(c for c in external_providers(db, NOW) if c["key"] == "gemini")

        assert "Not evidence" in (card["evidence_level"] or "")
        assert "checked against" in card["what_it_feeds"]
