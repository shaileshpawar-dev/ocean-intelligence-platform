r"""Step 0: prove each external credential works, without revealing any of them.

Every check reports PASS / FAIL / SKIP and a short reason. Nothing from .env
is ever printed, logged or included in an error message: responses are
summarised by status code and shape, and any text echoed back is truncated and
scrubbed of anything resembling a key.

Usage:
    python scripts/credential_smoke_test.py            # all checks
    python scripts/credential_smoke_test.py gemini cdse
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

TIMEOUT = 45.0

#: A small box off the Gujarat coast (Gulf of Kutch approaches). Chosen because
#: it is unambiguously Indian coastal water and tiny, so the Process API call
#: costs almost nothing against the free quota.
TEST_BBOX = [69.0, 22.2, 69.3, 22.5]


def load_env() -> dict[str, str]:
    """Read .env without exporting it or echoing anything."""
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


ENV = load_env()
SECRETS = {v for v in ENV.values() if v and len(v) >= 8}


def scrub(text: str, limit: int = 240) -> str:
    """Remove anything that looks like one of our secrets, then truncate.

    Belt and braces: an API that echoes a credential back in an error message
    must not get it into this script's output.
    """
    out = str(text)
    for secret in SECRETS:
        out = out.replace(secret, "<redacted>")
    out = re.sub(r"[A-Za-z0-9_\-]{32,}", "<redacted>", out)
    out = " ".join(out.split())
    return out[:limit]


def report(name: str, ok: bool | None, detail: str) -> None:
    status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    print(f"  [{status}] {name}: {detail}")


# ---------------------------------------------------------------------------
def check_gemini() -> None:
    key = ENV.get("GEMINI_API_KEY")
    if not key:
        report("Gemini", None, "GEMINI_API_KEY not set")
        return
    try:
        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key},
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        report("Gemini", False, f"{exc.__class__.__name__}: {scrub(exc)}")
        return

    if resp.status_code != 200:
        report("Gemini", False, f"HTTP {resp.status_code} {scrub(resp.text)}")
        return

    models = resp.json().get("models", [])
    usable = [
        m["name"].removeprefix("models/")
        for m in models
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    flash = [m for m in usable if "flash" in m and "thinking" not in m]
    # Prefer a stable, non-preview flash build for a demo.
    stable = [m for m in flash if not any(t in m for t in ("preview", "exp", "-lite"))]
    chosen = (stable or flash or usable or ["<none>"])[0]
    report(
        "Gemini",
        True,
        f"{len(usable)} generateContent models; flash candidates="
        f"{', '.join(flash[:6]) or 'none'}; RECOMMENDED={chosen}",
    )


# ---------------------------------------------------------------------------
def cdse_token() -> tuple[str | None, str]:
    """Return (token, detail). Password grant first, then client credentials."""
    url = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
        "/protocol/openid-connect/token"
    )
    attempts: list[tuple[str, dict[str, str]]] = []

    if ENV.get("CDSE_CLIENT_ID") and ENV.get("CDSE_CLIENT_SECRET"):
        attempts.append(
            (
                "client_credentials",
                {
                    "grant_type": "client_credentials",
                    "client_id": ENV["CDSE_CLIENT_ID"],
                    "client_secret": ENV["CDSE_CLIENT_SECRET"],
                },
            )
        )
    if ENV.get("CDSE_USERNAME") and ENV.get("CDSE_PASSWORD"):
        attempts.append(
            (
                "password",
                {
                    "grant_type": "password",
                    "client_id": "cdse-public",
                    "username": ENV["CDSE_USERNAME"],
                    "password": ENV["CDSE_PASSWORD"],
                },
            )
        )

    if not attempts:
        return None, "no CDSE credentials set"

    notes = []
    for label, payload in attempts:
        try:
            resp = httpx.post(url, data=payload, timeout=TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{label}: {exc.__class__.__name__}")
            continue
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            if token:
                return token, f"token via {label} grant"
            notes.append(f"{label}: 200 but no access_token")
        else:
            notes.append(f"{label}: HTTP {resp.status_code} {scrub(resp.text, 90)}")
    return None, "; ".join(notes)


def check_cdse() -> None:
    token, detail = cdse_token()
    if not token:
        report("CDSE token", False, detail)
        report("CDSE Process API", None, "no token")
        return
    report("CDSE token", True, detail)

    # One tiny true-colour request over the Indian coastal box.
    evalscript = """//VERSION=3
function setup() {
  return { input: ["B04","B03","B02"], output: { bands: 3 } };
}
function evaluatePixel(s) { return [s.B04, s.B03, s.B02]; }
"""
    body = {
        "input": {
            "bounds": {
                "bbox": TEST_BBOX,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": "2026-10-01T00:00:00Z",
                            "to": "2026-11-21T00:00:00Z",
                        },
                        "maxCloudCoverage": 40,
                    },
                }
            ],
        },
        "output": {
            "width": 32,
            "height": 32,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
    }
    try:
        resp = httpx.post(
            "https://sh.dataspace.copernicus.eu/api/v1/process",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        report("CDSE Process API", False, f"{exc.__class__.__name__}: {scrub(exc)}")
        return

    if resp.status_code == 200:
        report(
            "CDSE Process API",
            True,
            f"32x32 S2 L2A PNG over {TEST_BBOX}, {len(resp.content)} bytes",
        )
    else:
        report(
            "CDSE Process API",
            False,
            f"HTTP {resp.status_code} {scrub(resp.text, 200)}",
        )


# ---------------------------------------------------------------------------
def check_gfw() -> None:
    token = ENV.get("GFW_API_TOKEN")
    if not token:
        report("Global Fishing Watch", None, "GFW_API_TOKEN not set")
        return
    # v3 datasets listing is the cheapest authenticated call.
    try:
        resp = httpx.get(
            "https://gateway.api.globalfishingwatch.org/v3/datasets",
            headers={"Authorization": f"Bearer {token}"},
            # The endpoint rejects a bare request: limit must be >= 1 and
            # offset must accompany it.
            params={"limit": 10, "offset": 0},
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        report("Global Fishing Watch", False, f"{exc.__class__.__name__}: {scrub(exc)}")
        return

    if resp.status_code == 200:
        try:
            payload = resp.json()
            entries = payload.get("entries", payload if isinstance(payload, list) else [])
            report(
                "Global Fishing Watch",
                True,
                f"HTTP 200, {len(entries)} datasets visible",
            )
        except Exception:  # noqa: BLE001
            report("Global Fishing Watch", True, f"HTTP 200, {len(resp.content)} bytes")
    else:
        report(
            "Global Fishing Watch",
            False,
            f"HTTP {resp.status_code} {scrub(resp.text, 200)}",
        )


# ---------------------------------------------------------------------------
def check_cmems() -> None:
    try:
        import copernicusmarine  # noqa: F401
    except ImportError:
        report(
            "Copernicus Marine",
            None,
            "copernicusmarine toolbox not installed (pip install copernicusmarine)",
        )
        return

    import copernicusmarine as cm

    for label, user, pwd in (
        ("CMEMS", ENV.get("CMEMS_USERNAME"), ENV.get("CMEMS_PASSWORD")),
        ("CDSE", ENV.get("CDSE_USERNAME"), ENV.get("CDSE_PASSWORD")),
    ):
        if not (user and pwd):
            continue
        try:
            ok = cm.login(username=user, password=pwd, force_overwrite=True)
        except Exception as exc:  # noqa: BLE001
            report(
                f"Copernicus Marine ({label} creds)",
                False,
                f"{exc.__class__.__name__}: {scrub(exc, 160)}",
            )
            continue
        if ok is not False:
            report(f"Copernicus Marine ({label} creds)", True, "login accepted")
            return
        report(f"Copernicus Marine ({label} creds)", False, "login rejected")
    else:
        report("Copernicus Marine", None, "no usable credential pair")


CHECKS = {
    "gemini": check_gemini,
    "cdse": check_cdse,
    "gfw": check_gfw,
    "cmems": check_cmems,
}


def main(argv: list[str]) -> int:
    wanted = [a for a in argv[1:] if a in CHECKS] or list(CHECKS)
    print(f"Step 0 credential smoke test — {len(wanted)} check(s)")
    print(f"  .env: {'found' if ENV else 'MISSING'} ({len(ENV)} keys parsed)\n")
    for name in wanted:
        CHECKS[name]()
    print("\nNo credential values are printed by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
