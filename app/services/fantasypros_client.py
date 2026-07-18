"""Live FantasyPros Expert Consensus Rankings (ECR) scraped from the public
cheatsheet pages.

FantasyPros inlines its full consensus board as a ``var ecrData = {...}`` JS
variable on each cheatsheet page (no API key needed). We extract that JSON,
match its players to Sleeper player ids (so rookies with no NFL stats yet
still enter the pool), and cache the matched result for a few hours. The
entries carry FantasyPros tier and bye alongside ADP so the compare view can
surface them.
"""
from __future__ import annotations

import json
import time

import httpx

from app.services import names, sleeper_client

CHEATSHEET_URL = "https://www.fantasypros.com/nfl/rankings/{slug}-cheatsheets.php"
FORMAT_SLUG = {"standard": "standard", "half_ppr": "half-point-ppr", "ppr": "ppr"}
RELEVANT_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}


def _extract_ecr_json(html: str) -> dict:
    """Extract the JSON object assigned to ``ecrData`` on a cheatsheet page.

    Scans character-by-character from the first '{' after the ``ecrData``
    token, tracking brace depth while respecting quoted strings and
    backslash escapes, so a naive greedy regex can't overrun the object.
    """
    token = html.find("ecrData")
    if token == -1:
        raise RuntimeError("ecrData not found in FantasyPros page")
    start = html.find("{", token)
    if start == -1:
        raise RuntimeError("ecrData object start not found")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1])
    raise RuntimeError("ecrData object end not found")


async def _fetch_html(fmt: str) -> str:
    url = CHEATSHEET_URL.format(slug=FORMAT_SLUG[fmt])
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        last_exc: Exception | None = None
        for _ in range(2):  # one retry on failure
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.text
            except Exception as exc:  # network/HTTP error -> retry once
                last_exc = exc
        raise RuntimeError(f"FantasyPros request failed: {last_exc}")


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


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_entries(fmt: str) -> list[dict]:
    """Returns [{player_id, rank, name, position, team, adp, tier, bye, sos}]
    sorted by rank (re-numbered 1..N over successfully matched players)."""
    if fmt not in FORMAT_SLUG:
        raise KeyError(f"unknown format {fmt}")

    cached = _cache.get(fmt)
    if cached and time.time() - cached[0] < _TTL_SECONDS:
        return cached[1]

    html = await _fetch_html(fmt)
    data = _extract_ecr_json(html)
    players = data.get("players") or []
    if not players:
        raise RuntimeError("no FantasyPros data")

    index = await _build_name_index()
    entries: list[dict] = []
    seen: set[str] = set()
    for item in sorted(players, key=lambda r: _to_int(r.get("rank_ecr")) or 10**9):
        raw_name = item.get("player_name") or ""
        position = (
            (item.get("player_position_id") or "")
            .upper()
            .replace("DST", "DEF")
            .replace("PK", "K")
        )

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
                "team": item.get("player_team_id") or "FA",
                "adp": _to_float(item.get("rank_ave")),
                "tier": _to_int(item.get("tier")),
                "bye": _to_int(item.get("player_bye_week")),
                "sos": item.get("sos"),
            }
        )

    if len(entries) < 50:
        raise RuntimeError("no FantasyPros data")

    _cache[fmt] = (time.time(), entries)
    return entries
