"""Look up Monetate experience dates (test period, 100% date, end) from the Monetate Metadata API.

Why
---
For clients on Monetate (e.g. Domino's), winners usually go to 100% in Monetate straight after the
test, and stay there until they're built natively. The change date for a post-release check is the date
the 100% experience started, not the release date. This module pulls every experience's status, start
and end times and traffic splits so you don't have to dig through the Monetate interface.

What the API can and can't tell you (checked against developer.monetate.com, Nov 2026)
-------------------------------------------------------------------------------------
* ``GET /api/metadata/v1/{retailer}/production/metadata/experience-summary`` returns, per experience:
  ``experience_name``, ``status`` (active / draft / paused / scheduled / ended), ``create_time``,
  ``start_time``, ``end_time``, ``variant_splits`` (each variant's share of traffic), ``tags``, ``archived``.
* If a winner is set live as its **own experience** (e.g. "EXP283 - LIVE 100%"), its ``start_time`` is the
  100% date and its single variant at a split of 1.0 confirms it. This module flags those.
* If instead the **test experience's split was edited** to 100%, the API only shows today's split: there's
  no last-modified date or change history. Use "View Experience History" in Monetate, or
  recipes/sql/dominos_experiment_timeline.sql (GA4), to find the date.
* No results (sessions, conversions) are available from the API.

Credentials (never commit them)
-------------------------------
Each client needs a Monetate API key: generate an RSA key pair, upload the PUBLIC key in Monetate under
Settings > Sites > API Keys, and note the API username. Then store, per client:

* Streamlit Community Cloud / 120F hosting: in the app's **Secrets** (same format as
  .streamlit/secrets.toml.example)::

      [monetate.dominos]
      retailer = "dominos"          # retailer shortname in Monetate API URLs
      username = "api-user-name"
      private_key = \"\"\"-----BEGIN PRIVATE KEY-----
      ...
      -----END PRIVATE KEY-----\"\"\"

* GitHub Actions or a terminal: environment variables ``MONETATE_DOMINOS_RETAILER``,
  ``MONETATE_DOMINOS_USERNAME`` and ``MONETATE_DOMINOS_PRIVATE_KEY`` (the PEM text).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import pandas as pd

AUTH_URL = "https://api.monetate.net/api/auth/v0/refresh/"
API_BASE = "https://api.monetate.net/api/metadata/v1/{retailer}/production/metadata/"


@dataclass
class Credentials:
    client: str
    retailer: str
    username: str
    private_key: str


def _from_streamlit(client: str) -> dict | None:
    try:
        import streamlit as st
        sec = st.secrets.get("monetate", {})
        return dict(sec.get(client, {})) or None
    except Exception:  # noqa: BLE001 - no secrets file, not running in Streamlit, etc.
        return None


def get_credentials(client: str) -> Credentials | None:
    """Credentials for a client key such as 'dominos', from Streamlit secrets or environment variables."""
    c = _from_streamlit(client) or {}
    env = f"MONETATE_{client.upper()}_"
    retailer = c.get("retailer") or os.environ.get(env + "RETAILER")
    username = c.get("username") or os.environ.get(env + "USERNAME")
    key = c.get("private_key") or os.environ.get(env + "PRIVATE_KEY")
    if not (retailer and username and key):
        return None
    return Credentials(client, retailer, username, key.replace("\\n", "\n"))


def signed_jwt(creds: Credentials, now: float | None = None) -> str:
    """Short-lived JWT signed with the private key, exchanged for an access token."""
    import jwt  # PyJWT
    return jwt.encode({"iat": int(now if now is not None else time.time()), "username": creds.username},
                      creds.private_key, algorithm="RS256")


def access_token(creds: Credentials, session=None, ttl: int = 3600) -> str:
    import requests
    s = session or requests
    r = s.get(AUTH_URL, params={"ttl": ttl}, headers={"Authorization": f"JWT {signed_jwt(creds)}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Monetate authentication failed ({r.status_code}). Check the username, that the "
                           f"public key is uploaded and active in Monetate, and the private key. {r.text[:200]}")
    return r.json()["data"]["token"]


def fetch_experiences(creds: Credentials, name: str | None = None, session=None) -> list[dict]:
    """All experience summaries (optionally filtered by a case-insensitive name substring)."""
    import requests
    s = session or requests
    headers = {"Authorization": f"Token {access_token(creds, s)}"}
    url = API_BASE.format(retailer=creds.retailer) + "experience-summary"
    params = {"page_size": 1000, **({"name": name} if name else {})}
    out = []
    while url:
        r = s.get(url, params=params, headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Monetate experience list failed ({r.status_code}): {r.text[:200]}")
        body = r.json()
        out += body.get("data") or []
        url, params = (body.get("meta") or {}).get("next"), None   # 'next' already carries the query string
    return out


def _splits(exp: dict) -> list[tuple[str, float, bool]]:
    rows = []
    for v in exp.get("variant_splits") or []:
        is_ctrl = str(v.get("is_control", "")).lower() in ("true", "1", "yes") or v.get("variant") == "Control"
        rows.append((str(v.get("variant", "")), float(v.get("split") or 0), is_ctrl))
    return rows


def is_full_traffic(exp: dict) -> bool:
    """True if one non-control variant gets (almost) all traffic: a 100% / 'winner live' experience."""
    sp = _splits(exp)
    if not sp:
        return False
    live = [s for _, s, ctrl in sp if not ctrl]
    ctrl = sum(s for _, s, c in sp if c)
    return bool(live) and max(live) >= 0.99 and ctrl <= 0.01


def experiences_table(experiences: list[dict]) -> pd.DataFrame:
    rows = []
    for e in experiences:
        sp = _splits(e)
        rows.append({
            "experience": e.get("experience_name"),
            "status": e.get("status"),
            "100% experience": is_full_traffic(e),
            "start": e.get("start_time"),
            "end": e.get("end_time"),
            "created": e.get("create_time"),
            "splits": ", ".join(f"{v} {s:.0%}" for v, s, _ in sp),
            "tags": ", ".join(e.get("tags") or []),
            "archived": e.get("archived"),
            "id": e.get("id"),
        })
    t = pd.DataFrame(rows, columns=["experience", "status", "100% experience", "start", "end", "created", "splits",
                                    "tags", "archived", "id"])
    for c in ("start", "end", "created"):
        t[c] = pd.to_datetime(t[c], errors="coerce", utc=True).dt.tz_convert("Europe/London").dt.tz_localize(None)
    return t.sort_values("start", ascending=False, na_position="last").reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    """Command line: python -m impact_tool.monetate dominos [name filter] > experiences.csv"""
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    creds = get_credentials(args[0])
    if creds is None:
        print(f"No Monetate credentials for '{args[0]}'. See the module docstring.", file=sys.stderr)
        return 1
    experiences_table(fetch_experiences(creds, args[1] if len(args) > 1 else None)).to_csv(sys.stdout, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
