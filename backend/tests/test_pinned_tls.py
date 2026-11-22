"""Pinning is narrower than a CA chain, and must stay that way.

The risk this file guards is that someone reads ``verify_mode = CERT_NONE``
in ``pinned_tls`` and concludes the module disables verification, then
"simplifies" it by applying the same context everywhere. That would turn a
check that accepts exactly one certificate into one that accepts any
certificate from anyone.

So: the scope is pinned by test, the mismatch raises rather than warns, and
no host outside the list can obtain a pinned context.

Nothing here opens a socket.
"""

from __future__ import annotations

import hashlib

import pytest
from app.water.pinned_tls import (
    PINNED_HOSTS,
    PinnedCertificateMismatch,
    context_for,
    fingerprint_of,
    is_pinned,
    verify_pinned_host,
)

NWDP = "nwdp.nwic.gov.in"


class TestTheScopeIsExactlyTwoHosts:
    """Everything else must keep full chain verification."""

    def test_only_the_nwdp_host_is_pinned(self):
        assert set(PINNED_HOSTS) == {NWDP}

    def test_an_unpinned_host_gets_no_pinned_context(self, monkeypatch):
        """None means "use your normal verification", which is the default
        for every other host in the platform."""
        monkeypatch.setattr(
            "app.water.pinned_tls.fetch_leaf_fingerprint",
            lambda *a, **k: pytest.fail("an unpinned host must not be probed"),
        )

        assert context_for("https://generativelanguage.googleapis.com/v1beta") is None
        assert context_for("https://rtwqmsdb1.cpcb.gov.in/x.json") is None
        assert context_for("example.com") is None

    def test_a_lookalike_hostname_is_not_pinned(self):
        """Substring matching here would pin an attacker's domain."""
        for host in (
            "nwdp.nwic.gov.in.evil.test",
            "evil-nwdp.nwic.gov.in.example",
            "notnwdp.nwic.gov.in",
        ):
            assert not is_pinned(host), host

    def test_the_host_is_recognised_in_a_url_and_bare(self):
        assert is_pinned(NWDP)
        assert is_pinned(f"https://{NWDP}/api/3/action/package_search?rows=1")
        assert is_pinned(f"{NWDP}:443")

    def test_verifying_an_unpinned_host_refuses(self):
        with pytest.raises(PinnedCertificateMismatch, match="not a pinned host"):
            verify_pinned_host("example.com")


class TestAChangedCertificateStopsEverything:
    """A renewal and an interception look the same from here."""

    def test_a_different_fingerprint_raises(self, monkeypatch):
        monkeypatch.setattr(
            "app.water.pinned_tls.fetch_leaf_fingerprint",
            lambda *a, **k: "f" * 64,
        )

        with pytest.raises(PinnedCertificateMismatch) as caught:
            verify_pinned_host(NWDP)

        message = str(caught.value)
        assert "expected" in message and "received" in message
        assert PINNED_HOSTS[NWDP] in message, "the human needs both to compare"
        assert "Nothing was fetched" in message

    def test_a_mismatch_does_not_yield_a_context(self, monkeypatch):
        """The ordering that makes this safe: verify first, build second."""
        monkeypatch.setattr(
            "app.water.pinned_tls.fetch_leaf_fingerprint",
            lambda *a, **k: "0" * 64,
        )

        with pytest.raises(PinnedCertificateMismatch):
            context_for(f"https://{NWDP}/api/3/action/status_show")

    def test_the_matching_fingerprint_is_accepted(self, monkeypatch):
        monkeypatch.setattr(
            "app.water.pinned_tls.fetch_leaf_fingerprint",
            lambda *a, **k: PINNED_HOSTS[NWDP],
        )

        assert context_for(f"https://{NWDP}/api/3/action/status_show") is not None


class TestTheFingerprint:
    """SHA-256 over the DER bytes, which is what the pin records."""

    def test_it_is_the_sha256_of_the_der(self):
        assert fingerprint_of(b"certificate") == hashlib.sha256(
            b"certificate"
        ).hexdigest()

    def test_the_stored_pin_is_a_lowercase_hex_digest(self):
        """A colon-separated or uppercase pin pasted from openssl would never
        match, and would fail as "certificate changed" rather than as a typo."""
        pin = PINNED_HOSTS[NWDP]

        assert len(pin) == 64
        assert pin == pin.lower()
        assert all(c in "0123456789abcdef" for c in pin)
