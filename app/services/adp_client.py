"""Live preseason ADP from Fantasy Football Calculator's free public API.

FFC aggregates real mock drafts continuously through the preseason, exposed
per scoring format with no API key. We match FFC names to Sleeper player ids
(so rookies with no NFL stats yet still enter the draft pool) and cache the
matched result for a few hours.
"""
from __future__ import annotations

import datetime
import time

import httpx

from app.services import names, sleeper_client

ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}"
FORMAT_MAP = {"standard": "standard", "half_ppr": "half-ppr", "ppr": "ppr"}
RELEVANT_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}


def _season_year() -> int:
    # ADP for the upcoming season; before March the "upcoming" season is
    # still last calendar year's dataset on FFC.
    today = datetime.date.today()
    return today.year if today.month >= 3 else today.year - 1


async def _fetch_raw(fmt: str) -> list[dict]:
    url = ADP_URL.format(fmt=FORMAT_MAP[fmt])
    async with httpx.AsyncClient(timeout=20.0) as client:
        for year in (_season_year(), _season_year() - 1):
            resp = await client.get(url, params={"teams": 12, "year": year})
            if resp.status_code != 200:
                continue
            players = resp.json().get("players") or []
            if players:
                return players
    return []


async def _build_name_index() -> dict[str, list[tuple[str, dict]]]:
    directory = await sleeper_client.fetch_players()
    index: dict[str, list[tuple[str, dict]]] = {}
    for pid, info in directory.items():
        if not isinstance(info, dict):
            continue
        if info.get("position") not in RELEVANT_POSITIONS:
            continue
        full_name = info.get("full_name") or ""
        if not full_name:
            continue
        index.setdefault(names.normalize_name(full_name), []).append((pid, info))
    return index


async def fetch_entries(fmt: str) -> list[dict]:
    """Returns [{player_id, rank, name, position, team, adp}] sorted by ADP."""
    if fmt not in FORMAT_MAP:
        raise KeyError(f"unknown format {fmt}")

    cached = _cache.get(fmt)
    if cached and time.time() - cached[0] < _TTL_SECONDS:
        return cached[1]

    raw = await _fetch_raw(fmt)
    if not raw:
        raise RuntimeError("no ADP data available from provider")

    index = await _build_name_index()
    entries: list[dict] = []
    seen: set[str] = set()
    for item in sorted(raw, key=lambda r: r.get("adp") or 999):
        raw_name = item.get("name") or ""
        position = (item.get("position") or "").upper().replace("PK", "K").replace("DST", "DEF")

        pid = None
        if position == "DEF":
            pid = names.match_defense(raw_name, "DEF")
        else:
            candidates = index.get(names.normalize_name(raw_name), [])
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
        entries.append(
            {
                "player_id": pid,
                "rank": len(entries) + 1,
                "name": raw_name,
                "position": position,
                "team": item.get("team") or "FA",
                "adp": item.get("adp"),
                "bye": item.get("bye"),
            }
        )

    _cache[fmt] = (time.time(), entries)
    return entries
