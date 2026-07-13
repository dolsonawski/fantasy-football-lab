"""Imported leagues (ESPN / Sleeper): all teams + rosters, persisted to disk
so the trade analyzer can work directly off real league context."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.paths import DATA_DIR
from app.services import sleeper_client, espn_client

_USERS_DIR = DATA_DIR / "users"


def _dir(user_id: str) -> Path:
    d = _USERS_DIR / user_id / "leagues"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(user_id: str, key: str) -> Path:
    return _dir(user_id) / f"{key}.json"


def _save(user_id: str, league: dict) -> dict:
    league["key"] = f"{league['platform']}_{league['league_id']}"
    league["imported_at"] = int(time.time())
    _path(user_id, league["key"]).write_text(json.dumps(league, indent=1), encoding="utf-8")
    return league


async def import_sleeper_league(user_id: str, league_id: str) -> dict:
    try:
        rosters = await sleeper_client.fetch_league_rosters(league_id)
    except httpx.HTTPStatusError:
        raise ValueError(f"Sleeper league {league_id} not found")
    if not rosters:
        raise ValueError(f"Sleeper league {league_id} not found or has no rosters")
    try:
        users = await sleeper_client.fetch_league_users(league_id)
    except Exception:
        users = []
    users_by_id = {u.get("user_id"): u for u in users}

    teams = []
    for r in rosters:
        owner = users_by_id.get(r.get("owner_id")) or {}
        name = (
            (owner.get("metadata") or {}).get("team_name")
            or owner.get("display_name")
            or f"Team {r.get('roster_id')}"
        )
        teams.append(
            {
                "team_id": str(r.get("roster_id")),
                "name": name,
                "players": r.get("players") or [],
                "unmatched": [],
            }
        )
    return _save(user_id, {"platform": "sleeper", "league_id": str(league_id),
                           "name": f"Sleeper League {league_id}", "teams": teams})


async def import_espn_league(user_id: str, league_id: str, espn_s2: str | None, swid: str | None) -> dict:
    league = await espn_client.fetch_league(league_id, espn_s2, swid)
    return _save(user_id, league)


def list_leagues(user_id: str) -> list[dict]:
    out = []
    for path in sorted(_dir(user_id).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            out.append(
                {
                    "key": data["key"],
                    "platform": data["platform"],
                    "league_id": data["league_id"],
                    "name": data.get("name"),
                    "team_count": len(data.get("teams", [])),
                    "imported_at": data.get("imported_at"),
                }
            )
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return out


def get_league(user_id: str, key: str) -> dict | None:
    path = _path(user_id, key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def delete_league(user_id: str, key: str) -> bool:
    path = _path(user_id, key)
    if path.exists():
        path.unlink()
        return True
    return False
