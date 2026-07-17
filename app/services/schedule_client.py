"""Playoff-schedule strength (fantasy weeks 15-17).

Fetches each NFL team's regular-season schedule from ESPN's public site API
(no auth required), caches it to disk with a 24h TTL (same pattern as
sleeper_client), and computes a 1-5 star playoff strength-of-schedule
rating per team: 5 stars = easiest projected weeks 15-17 opponents.

Team "strength" itself is derived from the app's own projections dataset
(sum of the top 8 projected PPR points on that team's roster, normalized
0-1 across all 32 teams) rather than an external power rating, so it's
consistent with the rest of the app's valuations.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

from app.paths import CACHE_DIR
from app.services import dataset, names

SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/schedule"
_TTL_SECONDS = 24 * 60 * 60
_SCHEDULE_DIR = CACHE_DIR / "schedule"
_SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)

PLAYOFF_WEEKS = (15, 16, 17)

# The app's canonical team abbreviations (names.TEAM_DEFENSES values) match
# ESPN's site-API team slugs except for a couple of teams.
_TO_ESPN_SLUG = {"WAS": "wsh"}
_FROM_ESPN_ABBR = {"WSH": "WAS"}

_ALL_TEAMS = sorted(set(names.TEAM_DEFENSES.values()))


def _espn_slug(team: str) -> str:
    return _TO_ESPN_SLUG.get(team, team).lower()


def _cache_path(team: str) -> Path:
    return _SCHEDULE_DIR / f"{team}.json"


def _read_cache(team: str) -> dict | None:
    path = _cache_path(team)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > _TTL_SECONDS:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(team: str, data: dict) -> None:
    try:
        _cache_path(team).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


async def _fetch_team_schedule(team: str) -> dict[str, dict]:
    """{week_number (str) -> {"opp": abbr (our canonical form), "home": bool}}
    for this team's regular season. Returns {} on any failure — fetch or
    parse problems must degrade gracefully rather than break callers."""
    cached = _read_cache(team)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(SCHEDULE_URL.format(team=_espn_slug(team)))
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}

    out: dict[str, dict] = {}
    try:
        own_abbr = (data.get("team") or {}).get("abbreviation")
        for event in data.get("events") or []:
            season_type = (event.get("seasonType") or {}).get("type")
            if season_type != 2:  # 2 = regular season on ESPN's site API
                continue
            week = (event.get("week") or {}).get("number")
            if not week:
                continue
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competitors = competitions[0].get("competitors") or []
            own_c = next((c for c in competitors if (c.get("team") or {}).get("abbreviation") == own_abbr), None)
            opp_c = next((c for c in competitors if (c.get("team") or {}).get("abbreviation") != own_abbr), None)
            if not opp_c:
                continue
            opp_abbr_espn = (opp_c.get("team") or {}).get("abbreviation")
            if not opp_abbr_espn:
                continue
            out[str(week)] = {
                "opp": _FROM_ESPN_ABBR.get(opp_abbr_espn, opp_abbr_espn),
                "home": (own_c or {}).get("homeAway") == "home",
            }
    except (AttributeError, TypeError, KeyError):
        return {}

    if out:
        _write_cache(team, out)
    return out


async def team_week_opponent(team: str, week: int) -> dict | None:
    """{"opponent": abbr, "home": bool} for a team's given week, or None on
    a bye week / unrecognized team / schedule-fetch failure."""
    if not team or team == "FA":
        return None
    sched = await _fetch_team_schedule(team)
    entry = sched.get(str(week))
    if not entry:
        return None
    return {"opponent": entry["opp"], "home": entry["home"]}


async def matchup_difficulty(opponent: str | None) -> str | None:
    """'tough' or 'easy' for playing this opponent, based on normalized
    team strength; None when the opponent or strength data is unavailable."""
    if not opponent:
        return None
    strength = await team_strength()
    val = strength.get(opponent)
    if val is None:
        return None
    return "tough" if val >= 0.5 else "easy"


async def team_strength() -> dict[str, float]:
    """{team_abbr: 0-1 normalized offensive strength} from the top 8
    projected-PPR players on each NFL team's roster."""
    try:
        players = await dataset.build_dataset()
    except Exception:
        return {}

    totals: dict[str, list[float]] = {}
    for p in players:
        team = p.get("team")
        if not team or team == "FA":
            continue
        totals.setdefault(team, []).append((p.get("proj_points") or {}).get("ppr") or 0.0)

    sums = {team: sum(sorted(pts, reverse=True)[:8]) for team, pts in totals.items()}
    if not sums:
        return {}
    lo, hi = min(sums.values()), max(sums.values())
    span = (hi - lo) or 1.0
    return {team: (v - lo) / span for team, v in sums.items()}


_sos_cache: dict = {"data": None, "built_at": 0}
_SOS_TTL_SECONDS = 6 * 60 * 60


async def playoff_sos() -> dict[str, dict]:
    """{team_abbr: {"stars": 1-5, "opponents": [wk15, wk16, wk17]}}.

    5 stars = easiest projected schedule over fantasy weeks 15-17 (lowest
    average opponent strength); opponents entries are None for a bye week
    or when the schedule couldn't be fetched. Returns {} if the underlying
    schedule fetch and team-strength computation both fail."""
    if _sos_cache["data"] is not None and time.time() - _sos_cache["built_at"] < _SOS_TTL_SECONDS:
        return _sos_cache["data"]

    strength = await team_strength()
    if not strength:
        return {}

    schedules = await asyncio.gather(*(_fetch_team_schedule(t) for t in _ALL_TEAMS))

    avg_by_team: dict[str, float | None] = {}
    opp_by_team: dict[str, list[str | None]] = {}
    for team, sched in zip(_ALL_TEAMS, schedules):
        opponents = [(sched.get(str(w)) or {}).get("opp") for w in PLAYOFF_WEEKS]
        opp_by_team[team] = opponents
        opp_strengths = [strength[o] for o in opponents if o and o in strength]
        avg_by_team[team] = (sum(opp_strengths) / len(opp_strengths)) if opp_strengths else None

    valid_avgs = [v for v in avg_by_team.values() if v is not None]
    if not valid_avgs:
        return {}
    lo, hi = min(valid_avgs), max(valid_avgs)
    span = (hi - lo) or 1.0

    out: dict[str, dict] = {}
    for team in _ALL_TEAMS:
        avg = avg_by_team[team]
        if avg is None:
            continue
        ease = 1 - (avg - lo) / span  # lower opponent strength = easier = more stars
        stars = max(1, min(5, round(1 + ease * 4)))
        out[team] = {"stars": stars, "opponents": opp_by_team[team]}

    _sos_cache["data"] = out
    _sos_cache["built_at"] = time.time()
    return out
