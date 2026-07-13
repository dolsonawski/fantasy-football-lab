"""ESPN fantasy football public API client.

Two things come from here, no auth required:
- Platform-wide player rankings/ADP (kona_player_info on the default
  league) — ESPN's own draft ranks per scoring type plus live ADP from
  real ESPN drafts. This is the board the app compares against to find
  mis-ranked players on ESPN.
- League imports: public league rosters/teams by league id (private
  leagues work when the user supplies their espn_s2 + SWID cookies).
"""
from __future__ import annotations

import datetime
import json
import time

import httpx

from app.services import names, sleeper_client

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"

POSITION_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA",
    16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI",
    23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR",
    30: "JAX", 33: "BAL", 34: "HOU",
}

# ESPN publishes STANDARD and PPR expert ranks; half-PPR leagues use PPR.
RANK_TYPE_FOR_FORMAT = {"standard": "STANDARD", "half_ppr": "PPR", "ppr": "PPR"}

_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
_NEWS_TTL = 20 * 60
_news_cache: dict[str, tuple[float, list[dict]]] = {}


async def fetch_general_news(limit: int = 60) -> list[dict]:
    """Recent league-wide NFL headlines (cached). ESPN doesn't expose free
    per-athlete news, so per-player news is derived by matching names against
    this feed."""
    cached = _news_cache.get("all")
    if cached and time.time() - cached[0] < _NEWS_TTL:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(NEWS_URL, params={"limit": limit})
            resp.raise_for_status()
            articles = resp.json().get("articles") or []
    except httpx.HTTPError:
        return _news_cache.get("all", (0, []))[1]

    items = []
    for a in articles:
        link = (((a.get("links") or {}).get("web") or {}).get("href"))
        img = None
        imgs = a.get("images") or []
        if imgs:
            img = imgs[0].get("url")
        items.append(
            {
                "headline": a.get("headline") or "",
                "description": a.get("description") or "",
                "published": a.get("published"),
                "link": link,
                "image": img,
            }
        )
    _news_cache["all"] = (time.time(), items)
    return items


async def player_news(full_name: str, limit: int = 5) -> list[dict]:
    """Headlines from the general feed that mention this player by name."""
    if not full_name:
        return []
    articles = await fetch_general_news()
    name = full_name.lower()
    parts = name.split()
    last = parts[-1] if parts else name
    out = []
    for a in articles:
        blob = (a["headline"] + " " + a["description"]).lower()
        # Full name is a strong match; last name only if it's distinctive (>3 chars).
        if name in blob or (len(last) > 3 and last in blob):
            out.append(a)
        if len(out) >= limit:
            break
    return out


def _season_year() -> int:
    today = datetime.date.today()
    return today.year if today.month >= 3 else today.year - 1


async def _fetch_kona_players(season: int) -> list[dict]:
    url = BASE.format(season=season) + "/segments/0/leaguedefaults/3"
    fltr = {"players": {"limit": 400, "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "PPR"}}}
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.get(
            url,
            params={"view": "kona_player_info"},
            headers={"X-Fantasy-Filter": json.dumps(fltr)},
        )
        resp.raise_for_status()
        return resp.json().get("players") or []


async def _matched_players(season: int) -> list[dict]:
    """Raw ESPN players matched to Sleeper ids, with ranks/adp attached."""
    raw = await _fetch_kona_players(season)
    directory = await sleeper_client.fetch_players()

    index: dict[str, list[tuple[str, dict]]] = {}
    for pid, info in directory.items():
        if not isinstance(info, dict):
            continue
        if info.get("position") not in sleeper_client.RELEVANT_POSITIONS:
            continue
        full_name = info.get("full_name") or ""
        if full_name:
            index.setdefault(names.normalize_name(full_name), []).append((pid, info))

    matched = []
    seen: set[str] = set()
    for item in raw:
        player = item.get("player") or {}
        full_name = player.get("fullName") or ""
        position = POSITION_MAP.get(player.get("defaultPositionId"))
        if not full_name or not position:
            continue

        pid = None
        if position == "DEF":
            pid = names.match_defense(full_name, "DEF")
        else:
            candidates = index.get(names.normalize_name(full_name), [])
            if len(candidates) > 1:
                filtered = [c for c in candidates if c[1].get("position") == position]
                candidates = filtered or candidates
            if len(candidates) > 1:
                candidates.sort(key=lambda c: c[1].get("search_rank") or 10**9)
            if candidates:
                pid = candidates[0][0]
        if pid is None or pid in seen:
            continue
        seen.add(pid)

        ranks = player.get("draftRanksByRankType") or {}
        ownership = player.get("ownership") or {}
        adp = ownership.get("averageDraftPosition")
        matched.append(
            {
                "player_id": pid,
                "name": full_name,
                "position": position,
                "team": PRO_TEAMS.get(player.get("proTeamId"), "FA"),
                "adp": round(float(adp), 1) if isinstance(adp, (int, float)) and adp > 0 else None,
                "rank_standard": (ranks.get("STANDARD") or {}).get("rank"),
                "rank_ppr": (ranks.get("PPR") or {}).get("rank"),
            }
        )
    return matched


async def fetch_rank_entries(fmt: str) -> list[dict]:
    """ESPN expert draft rank board for a format."""
    cache_key = f"rank_{fmt}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _TTL_SECONDS:
        return cached[1]

    matched = await _matched_players(_season_year())
    rank_field = "rank_standard" if RANK_TYPE_FOR_FORMAT[fmt] == "STANDARD" else "rank_ppr"
    ranked = [m for m in matched if isinstance(m.get(rank_field), int)]
    ranked.sort(key=lambda m: m[rank_field])
    entries = [
        {**m, "rank": i + 1}
        for i, m in enumerate(ranked)
    ]
    _cache[cache_key] = (time.time(), entries)
    return entries


async def fetch_adp_entries(fmt: str) -> list[dict]:
    """ESPN live ADP board (ESPN ADP is not format-split; same for all)."""
    cached = _cache.get("adp")
    if cached and time.time() - cached[0] < _TTL_SECONDS:
        return cached[1]

    matched = await _matched_players(_season_year())
    ranked = [m for m in matched if m.get("adp") is not None]
    ranked.sort(key=lambda m: m["adp"])
    entries = [{**m, "rank": i + 1} for i, m in enumerate(ranked)]
    _cache["adp"] = (time.time(), entries)
    return entries


# ---------------------------------------------------------------- leagues

async def fetch_league(league_id: str, espn_s2: str | None = None, swid: str | None = None) -> dict:
    """Fetches an ESPN league's teams + rosters (public, or private with cookies)."""
    season = _season_year()
    url = BASE.format(season=season) + f"/segments/0/leagues/{league_id}"
    cookies = {}
    if espn_s2 and swid:
        cookies = {"espn_s2": espn_s2, "SWID": swid}

    async with httpx.AsyncClient(timeout=25.0, cookies=cookies) as client:
        resp = await client.get(url, params=[("view", "mRoster"), ("view", "mTeam"), ("view", "mSettings")])
        if resp.status_code == 401:
            raise ValueError(
                "This ESPN league is private. Supply your espn_s2 and SWID cookies to import it."
            )
        if resp.status_code == 404:
            raise ValueError(f"ESPN league {league_id} not found for the {season} season.")
        resp.raise_for_status()
        data = resp.json()

    directory = await sleeper_client.fetch_players()
    index: dict[str, list[tuple[str, dict]]] = {}
    for pid, info in directory.items():
        if not isinstance(info, dict) or info.get("position") not in sleeper_client.RELEVANT_POSITIONS:
            continue
        full_name = info.get("full_name") or ""
        if full_name:
            index.setdefault(names.normalize_name(full_name), []).append((pid, info))

    teams = []
    for team in data.get("teams") or []:
        team_name = team.get("name") or f"{team.get('location', '')} {team.get('nickname', '')}".strip() or f"Team {team.get('id')}"
        player_ids, unmatched = [], []
        for entry in ((team.get("roster") or {}).get("entries")) or []:
            player = ((entry.get("playerPoolEntry") or {}).get("player")) or {}
            full_name = player.get("fullName") or ""
            position = POSITION_MAP.get(player.get("defaultPositionId"))
            pid = None
            if position == "DEF":
                pid = names.match_defense(full_name, "DEF")
            else:
                candidates = index.get(names.normalize_name(full_name), [])
                if len(candidates) > 1 and position:
                    filtered = [c for c in candidates if c[1].get("position") == position]
                    candidates = filtered or candidates
                if len(candidates) > 1:
                    candidates.sort(key=lambda c: c[1].get("search_rank") or 10**9)
                if candidates:
                    pid = candidates[0][0]
            if pid:
                player_ids.append(pid)
            elif full_name:
                unmatched.append(full_name)
        teams.append(
            {
                "team_id": str(team.get("id")),
                "name": team_name,
                "players": player_ids,
                "unmatched": unmatched,
            }
        )

    league_name = ((data.get("settings") or {}).get("name")) or f"ESPN League {league_id}"
    return {"platform": "espn", "league_id": str(league_id), "name": league_name,
            "season": season, "teams": teams}
