"""A refusal is not an outage, and the card has to tell them apart.

When a server answers and declines, reporting it as "Unavailable" sends
somebody looking for a network fault that does not exist. The NWDP feeds are
exactly that case: the TLS handshake completes, the host is up, and a
firewall returns 403. The page should say so, in those words, beside the
number of records already held — and put the raw error behind a toggle,
because a stack trace on a card reads as breakage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.water import DataSource
from app.services.water_service import source_status

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def _source(**overrides) -> DataSource:
    base = {
        "key": "cpcb_nwdp",
        "name": "CPCB Surface Water Quality (Manual)",
        "organisation": "Central Pollution Control Board",
        "source_type": "government",
        "expected_cadence": "monthly",
        "is_available": False,
        "last_error": None,
        "last_success_at": NOW - timedelta(days=56),
    }
    return DataSource(**{**base, **overrides})


class TestARefusalIsNotAnOutage:
    """The distinction this module exists to draw."""

    def test_a_403_is_reported_as_sync_paused(self):
        status = source_status(
            _source(last_error="NWDP datastore_search failed: HTTP Error 403: Forbidden"),
            records_held=582_192,
            now=NOW,
        )

        assert status["state"] == "sync_paused"
        assert status["label"] == "Sync paused"
        assert status["tone"] == "warn", "amber, not red: nothing is broken here"
        assert "Blocked by upstream firewall" in status["detail"]
        assert "automated access refused (HTTP 403)" in status["detail"]

    def test_the_paused_card_shows_what_is_still_held(self):
        """"Sync paused" reads very differently beside half a million rows."""
        status = source_status(
            _source(last_error="HTTP Error 403: Forbidden"),
            records_held=582_192,
            now=NOW,
        )

        assert status["records_held"] == 582_192
        assert "last successful sync (26 Sep 2026)" in status["detail"]

    def test_an_unreachable_source_is_still_unavailable(self):
        """A genuine connection failure must keep reading as one."""
        status = source_status(
            _source(last_error="URLError: [Errno 11001] getaddrinfo failed"),
            records_held=0,
            now=NOW,
        )

        assert status["state"] == "unavailable"
        assert status["tone"] == "bad"
        assert "could not be reached" in status["detail"]

    def test_a_source_with_no_successful_sync_says_never(self):
        status = source_status(
            _source(last_success_at=None, last_error="timeout"),
            records_held=0,
            now=NOW,
        )

        assert "never" in status["detail"]


class TestAReachableSource:
    """Live while it is syncing, stale once its data ages out."""

    def test_a_current_source_is_live(self):
        status = source_status(
            _source(
                key="cpcb_rtwqms",
                is_available=True,
                expected_cadence="hourly",
                last_success_at=NOW - timedelta(hours=2),
                last_error=None,
            ),
            records_held=1_397,
            now=NOW,
        )

        assert status["state"] == "live"
        assert status["tone"] == "ok"

    def test_a_reachable_but_long_stale_source_is_stale(self):
        """Reachable and useless are compatible, and the page should say so."""
        status = source_status(
            _source(
                is_available=True,
                expected_cadence="monthly",
                last_success_at=NOW - timedelta(days=200),
                last_error=None,
            ),
            records_held=10,
            now=NOW,
        )

        assert status["state"] == "stale"
        assert status["tone"] == "warn"
        assert "older than" in status["detail"]


class TestTheRawErrorIsNotOnTheCard:
    """It belongs behind the Technical details toggle."""

    def test_the_raw_error_is_carried_separately(self):
        raw = "NWDP datastore_search failed after 3 attempts: HTTP Error 403: Forbidden"
        status = source_status(_source(last_error=raw), records_held=1, now=NOW)

        assert status["technical_detail"] == raw
        assert raw not in status["detail"], "the sentence must not be the stack trace"

    def test_a_healthy_source_has_nothing_to_hide(self):
        status = source_status(
            _source(is_available=True, last_error=None, last_success_at=NOW),
            records_held=1,
            now=NOW,
        )

        assert status["technical_detail"] is None


class TestTheRealFeeds:
    """Against the error strings actually stored by the ingestion pipeline."""

    @pytest.mark.parametrize("key", ["cpcb_nwdp", "cwc_nwdp"])
    def test_both_nwdp_feeds_read_as_paused(self, key):
        stored = (
            "Maharashtra — biological (1961-2020): NWDP datastore_search "
            "failed after 3 attempts: HTTP Error 403: Forbidden"
        )

        assert source_status(
            _source(key=key, last_error=stored), records_held=1, now=NOW
        )["state"] == "sync_paused"
