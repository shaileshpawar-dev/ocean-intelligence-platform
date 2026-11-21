"""Certificate pinning for two government hosts that no CA chain can cover.

**This is not "verification off".** Read the difference before changing
anything here, because the two look similar in a diff and are opposites.

Disabling verification accepts *any* certificate from *anyone* on the path.
What this module does is replace the chain check, for two named hosts only,
with a check that the server presents **one specific certificate** whose
SHA-256 fingerprint is recorded below. An attacker needs the private key for
that exact certificate. That is a narrower trust decision than a CA chain,
not a wider one: a public CA will vouch for any of millions of certificates,
and this will vouch for one.

**Why those hosts need it.** ``nwdp.nwic.gov.in`` serves the CPCB and CWC
water-quality datasets. It sits behind a Fortinet appliance presenting the
**FortiGate factory CA** certificate, which is in no public trust store, and
as of 20 November 2026 that certificate has also expired. Both failures are
the operator's, not ours, and neither is fixable from this side. The options
were to pin, or to keep reporting the national water feeds as unreachable.

**What this does not fix.** The FortiGate CA's private key ships on every
such appliance, so the *issuer* proves nothing. The pin is therefore on the
**leaf** certificate rather than the chain: it is the server's own key pair
that is being trusted, which is the strongest statement available here.

**When CPCB renews the certificate this will stop working, loudly.** That is
the intended behaviour. A changed fingerprint produces
:class:`PinnedCertificateMismatch` naming both fingerprints, and the fix is a
human looking at the new certificate and updating the constant below -- not
code that quietly accepts whatever arrives.

Every other host in the platform uses ordinary, full verification. Nothing in
this module is reachable for a host that is not in :data:`PINNED_HOSTS`.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from urllib.parse import urlparse

from app.core.logging import get_logger

logger = get_logger(__name__)


class PinnedCertificateMismatch(Exception):
    """A pinned host presented a certificate we do not recognise.

    Raised rather than logged. A mismatch is either the operator renewing
    their certificate -- which a person should confirm -- or someone sitting
    between us and a government server. Neither is something to continue past.
    """


#: host -> expected SHA-256 fingerprint of the **leaf** certificate, as the
#: lowercase hex digest of its DER encoding.
#:
#: nwdp.nwic.gov.in, recorded 21 November 2026:
#:   subject  CN=nwdp.nwic.gov.in
#:   issuer   CN=FortiGate CA, O=Fortinet          (factory appliance CA)
#:   validity 20 Nov 2025 -- 20 Nov 2026           (expired the day before)
PINNED_HOSTS: dict[str, str] = {
    "nwdp.nwic.gov.in": (
        "a3eb9d3be0ecb52905242c78fc993b8936fcbb12799804db00577eb76e9aa29a"
    ),
}


def is_pinned(host_or_url: str) -> bool:
    """Whether this host is one of the pinned ones."""
    return _host_of(host_or_url) in PINNED_HOSTS


def _host_of(host_or_url: str) -> str:
    """The bare hostname, whether given a host or a URL."""
    if "://" in host_or_url:
        return (urlparse(host_or_url).hostname or "").lower()
    return host_or_url.split("/")[0].split(":")[0].lower()


def fingerprint_of(der: bytes) -> str:
    """SHA-256 of a DER-encoded certificate, lowercase hex."""
    return hashlib.sha256(der).hexdigest()


def fetch_leaf_fingerprint(host: str, port: int = 443, timeout: float = 20.0) -> str:
    """Read a host's current leaf fingerprint, without trusting it.

    A diagnostic, used to tell "they renewed" from "something is wrong" when
    a pin fails, and to record a new pin for a human to confirm. It returns a
    fingerprint; it never decides that one is acceptable.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise PinnedCertificateMismatch(f"{host} presented no certificate.")
    return fingerprint_of(der)


def verify_pinned_host(host: str, port: int = 443, timeout: float = 20.0) -> None:
    """Confirm a pinned host still presents the certificate we recorded.

    Raises:
        PinnedCertificateMismatch: the host is not pinned, presented no
            certificate, or presented a different one. The message names both
            fingerprints so a human can compare them.
    """
    expected = PINNED_HOSTS.get(host.lower())
    if expected is None:
        raise PinnedCertificateMismatch(
            f"{host} is not a pinned host. Pinning is deliberately limited to "
            f"{sorted(PINNED_HOSTS)}; every other host uses full chain "
            "verification."
        )

    actual = fetch_leaf_fingerprint(host, port=port, timeout=timeout)
    if actual != expected:
        logger.warning("pinned_certificate_changed", extra={"host": host})
        raise PinnedCertificateMismatch(
            f"{host} presented a certificate this platform does not "
            f"recognise.\n  expected {expected}\n  received {actual}\n"
            "Nothing was fetched. If the operator has renewed their "
            "certificate, a person should inspect the new one and update "
            "PINNED_HOSTS in app/water/pinned_tls.py. This platform will not "
            "accept an unrecognised certificate on its own."
        )


def pinned_context(host: str) -> ssl.SSLContext:
    """An SSL context for a pinned host, after its certificate is confirmed.

    The ordering is the point: :func:`verify_pinned_host` runs **first** and
    raises on anything unexpected, so by the time a context is returned the
    certificate has already been matched against the pin. The returned
    context does not re-check the chain, because the chain is exactly what
    cannot be checked for these hosts -- the pin has replaced it.

    Raises:
        PinnedCertificateMismatch: as :func:`verify_pinned_host`.
    """
    verify_pinned_host(host)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Both off *only* because the fingerprint check above is stricter than
    # either: it accepts one certificate rather than any certificate a CA
    # will sign, and the hostname is how we chose the pin in the first place.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def context_for(host_or_url: str) -> ssl.SSLContext | None:
    """A pinned context for a pinned host, or ``None`` for everything else.

    ``None`` means "use the caller's normal verification", which is what
    every other host in the platform gets.
    """
    host = _host_of(host_or_url)
    if host not in PINNED_HOSTS:
        return None
    return pinned_context(host)
