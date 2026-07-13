"""Thin client for Sleeper's free public API, with on-disk caching.

Sleeper asks integrators not to hammer /players/nfl (it's a multi-MB dump of
every NFL player) more than once a day, so we cache aggressively to disk.
No API key is required for any of these endpoints.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.paths import CACHE_DIR as _CACHE_ROOT

BASE_URL = "https://api.sleeper.app/v1"
CACHE_DIR = _CACHE_ROOT
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PLAYERS_TTL_SECONDS = 24 * 60 * 60
STATS_TTL_SECONDS = 6 * 60 * 60

RELEVANT_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _read_cache(name: str, ttl_seconds: int) -> dict | None:
    path = _cache_path(name)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(name: str, data: dict) -> None:
    _cache_path(name).write_text(json.dumps(data), encoding="utf-8")


_players_mem: dict | None = None


async def fetch_players(force_refresh: bool = False) -> dict:
    """Returns {player_id: player_info} for every NFL player Sleeper knows about."""
    global _players_mem
    if not force_refresh:
        if _players_mem is not None:
            return _players_mem
        cached = _read_cache("players", PLAYERS_TTL_SECONDS)
        if cached is not None:
            _players_mem = cached
            return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BASE_URL}/players/nfl")
        resp.raise_for_status()
        data = resp.json()

    _write_cache("players", data)
    _players_mem = data
    return data


async def fetch_season_stats(season: str, season_type: str = "regular") -> dict:
    """Returns {player_id: stat_totals} aggregated over the given season."""
    cache_key = f"stats_{season_type}_{season}"
    cached = _read_cache(cache_key, STATS_TTL_SECONDS)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BASE_URL}/stats/nfl/{season_type}/{season}")
        resp.raise_for_status()
        data = resp.json()

    if data:
        _write_cache(cache_key, data)
    return data


async def fetch_season_projections(season: str, season_type: str = "regular") -> dict:
    """Returns {player_id: projected stat totals} for the given season.

    Includes pre-computed fantasy points (pts_std / pts_half_ppr / pts_ppr)
    and Sleeper's own per-format ADP (adp_std / adp_half_ppr / adp_ppr).
    """
    cache_key = f"proj_{season_type}_{season}"
    cached = _read_cache(cache_key, STATS_TTL_SECONDS)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BASE_URL}/projections/nfl/{season_type}/{season}")
        resp.raise_for_status()
        data = resp.json()

    if data:
        _write_cache(cache_key, data)
    return data


async def fetch_weekly_projections(season: str, week: int, season_type: str = "regular") -> dict:
    """Per-week projections {player_id: stats with pts_std/half/ppr}. Returns
    {} when Sleeper hasn't published that week yet (e.g. deep offseason)."""
    cache_key = f"projw_{season_type}_{season}_{week}"
    cached = _read_cache(cache_key, STATS_TTL_SECONDS)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BASE_URL}/projections/nfl/{season_type}/{season}/{week}")
        if resp.status_code != 200:
            return {}
        data = resp.json() or {}
    if data:
        _write_cache(cache_key, data)
    return data


async def fetch_draft(draft_id: str) -> dict:
    """A real Sleeper draft's metadata (status, settings, order)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{BASE_URL}/draft/{draft_id}")
        resp.raise_for_status()
        return resp.json()


async def fetch_draft_picks(draft_id: str) -> list:
    """All picks made so far in a real Sleeper draft."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{BASE_URL}/draft/{draft_id}/picks")
        resp.raise_for_status()
        return resp.json() or []


async def fetch_trending(kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/players/nfl/trending/{kind}",
            params={"lookback_hours": lookback_hours, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_league_rosters(league_id: str) -> list:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{BASE_URL}/league/{league_id}/rosters")
        resp.raise_for_status()
        return resp.json()


async def fetch_league_users(league_id: str) -> list:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{BASE_URL}/league/{league_id}/users")
        resp.raise_for_status()
        return resp.json()
