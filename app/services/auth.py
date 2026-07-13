"""Lightweight username/password auth for the local app.

Passwords are salted + hashed with PBKDF2-HMAC-SHA256 (stdlib only, no extra
deps). Users and sessions persist to disk so a dev-server restart doesn't
wipe accounts or force everyone to log back in. This is sized for a personal
/ small-group local tool — not a hardened public service.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path

from app.paths import DATA_DIR

USERS_FILE = DATA_DIR / "users.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"

COOKIE_NAME = "ffl_session"
SESSION_TTL = 60 * 60 * 24 * 180  # ~6 months; keeps each device signed in
_ITERATIONS = 200_000


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS
    ).hex()


def _public(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "created_at": user.get("created_at"),
    }


def create_user(username: str, password: str, display_name: str | None = None) -> dict:
    username = (username or "").strip()
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters.")
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters.")

    users = _load(USERS_FILE, {})
    if any(u["username"].lower() == username.lower() for u in users.values()):
        raise ValueError("That username is already taken.")

    uid = uuid.uuid4().hex[:12]
    salt = secrets.token_hex(16)
    users[uid] = {
        "id": uid,
        "username": username,
        "display_name": (display_name or username).strip() or username,
        "salt": salt,
        "pw_hash": _hash(password, salt),
        "created_at": int(time.time()),
    }
    _save(USERS_FILE, users)
    return _public(users[uid])


def verify_login(username: str, password: str) -> dict | None:
    users = _load(USERS_FILE, {})
    username = (username or "").strip().lower()
    for user in users.values():
        if user["username"].lower() == username:
            expected = user["pw_hash"]
            actual = _hash(password or "", user["salt"])
            if hmac.compare_digest(expected, actual):
                return _public(user)
            return None
    return None


def create_session(user_id: str) -> str:
    sessions = _load(SESSIONS_FILE, {})
    token = secrets.token_urlsafe(32)
    sessions[token] = {"user_id": user_id, "created_at": int(time.time())}
    _save(SESSIONS_FILE, sessions)
    return token


def get_user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    sessions = _load(SESSIONS_FILE, {})
    session = sessions.get(token)
    if not session:
        return None
    if time.time() - session.get("created_at", 0) > SESSION_TTL:
        delete_session(token)
        return None
    users = _load(USERS_FILE, {})
    user = users.get(session["user_id"])
    return _public(user) if user else None


def delete_session(token: str | None) -> None:
    if not token:
        return
    sessions = _load(SESSIONS_FILE, {})
    if token in sessions:
        del sessions[token]
        _save(SESSIONS_FILE, sessions)
