"""Shared FastAPI dependencies.

No accounts, no passwords: each browser generates a random anonymous ID
client-side (see identity.js) and sends it as X-FFL-UID on every request.
That ID is used directly as the per-person storage namespace — the same
pattern draft_engine/league_store/season already key off of. This avoids
needing a persistent user database at all, which matters on hosts with no
persistent disk (the ID lives in the browser, not the server).
"""
from __future__ import annotations

import re

from fastapi import Header, HTTPException

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def current_user(x_ffl_uid: str | None = Header(default=None)) -> dict:
    if not x_ffl_uid or not _ID_RE.match(x_ffl_uid):
        raise HTTPException(status_code=400, detail="Missing or invalid X-FFL-UID header")
    return {"id": x_ffl_uid, "display_name": x_ffl_uid[:8]}
