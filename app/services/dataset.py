"""Builds the in-memory player value dataset from real Sleeper data.

Each record combines:
- last season's real stat totals, scored under three formats ("points",
  "vbd", production ranks) — the *what actually happened* view; and
- Sleeper's projections for the upcoming season ("proj_points",
  "proj_vbd", projection ranks, plus Sleeper's own per-format ADP) — the
  *what to expect* view that drives draft values, roster grades, and
  trade analysis.

Players who only exist in projections (rookies) still get full records.
"""
from __future__ import annotations

import time

from app.services import scoring, sleeper_client

# Most recently completed NFL regular season as of app launch. If Sleeper has
# no stats posted yet for this season, we fall back to the prior one.
PRIMARY_SEASON = "2025"
FALLBACK_SEASON = "2024"

# Upcoming season for projections (falls back if not published yet).
PROJECTION_SEASON = "2026"
PROJECTION_FALLBACK = "2025"

# Roughly how many players at each position are "startable" in a typical
# 12-team league (used as the VBD replacement-level baseline). This is a
# transparent heuristic, not a proprietary formula.
BASELINE_RANK = {"QB": 12, "RB": 24, "WR": 30, "TE": 12, "K": 12, "DEF": 12}

_ADP_UNRANKED = 900  # Sleeper uses 999.0 for "not being drafted"

_cache: dict = {"season": None, "proj_season": None, "players": None, "built_at": 0}
_CACHE_TTL_SECONDS = 6 * 60 * 60


def _display_name(pid: str, info: dict) -> str:
    name = info.get("full_name")
    if name:
        return name
    first, last = info.get("first_name"), info.get("last_name")
    if first or last:
        return f"{first or ''} {last or ''}".strip()
    return pid


def _market_rank(info: dict) -> int | None:
    rank = info.get("search_rank")
    if not isinstance(rank, (int, float)) or rank >= 900000:  # Sleeper's "unranked" sentinel
        return None
    return int(rank)


def _primary_position(info: dict) -> str | None:
    pos = info.get("position")
    if pos in sleeper_client.RELEVANT_POSITIONS:
        return pos
    for fp in info.get("fantasy_positions") or []:
        if fp in sleeper_client.RELEVANT_POSITIONS:
            return fp
    return None


async def _load_stats_for_best_season() -> tuple[str, dict]:
    stats = await sleeper_client.fetch_season_stats(PRIMARY_SEASON)
    if stats:
        return PRIMARY_SEASON, stats
    stats = await sleeper_client.fetch_season_stats(FALLBACK_SEASON)
    return FALLBACK_SEASON, stats


async def _load_projections() -> tuple[str | None, dict]:
    try:
        proj = await sleeper_client.fetch_season_projections(PROJECTION_SEASON)
        if proj:
            return PROJECTION_SEASON, proj
        proj = await sleeper_client.fetch_season_projections(PROJECTION_FALLBACK)
        if proj:
            return PROJECTION_FALLBACK, proj
    except Exception:
        pass
    return None, {}


def _proj_points(proj: dict) -> dict:
    return {
        "standard": round(float(proj.get("pts_std") or 0.0), 2),
        "half_ppr": round(float(proj.get("pts_half_ppr") or 0.0), 2),
        "ppr": round(float(proj.get("pts_ppr") or 0.0), 2),
    }


def _sleeper_adp(proj: dict) -> dict:
    out = {}
    for fmt, key in (("standard", "adp_std"), ("half_ppr", "adp_half_ppr"), ("ppr", "adp_ppr")):
        val = proj.get(key)
        out[fmt] = round(float(val), 1) if isinstance(val, (int, float)) and val < _ADP_UNRANKED else None
    return out


def _sleeper_dynasty_adp(proj: dict) -> dict:
    out = {}
    for fmt, key in (("standard", "adp_dynasty_std"), ("half_ppr", "adp_dynasty_half_ppr"), ("ppr", "adp_dynasty_ppr")):
        val = proj.get(key)
        out[fmt] = round(float(val), 1) if isinstance(val, (int, float)) and val < _ADP_UNRANKED else None
    return out


async def build_dataset(force_refresh: bool = False) -> list[dict]:
    if (
        not force_refresh
        and _cache["players"] is not None
        and time.time() - _cache["built_at"] < _CACHE_TTL_SECONDS
    ):
        return _cache["players"]

    players = await sleeper_client.fetch_players(force_refresh=force_refresh)
    season, stats_by_id = await _load_stats_for_best_season()
    proj_season, proj_by_id = await _load_projections()

    zeros = {fmt: 0.0 for fmt in scoring.SCORING_FORMATS}
    records: list[dict] = []
    for pid in set(stats_by_id) | set(proj_by_id):
        info = players.get(pid)
        if not info:
            continue
        position = _primary_position(info)
        if not position:
            continue

        player_stats = stats_by_id.get(pid) or {}
        proj = proj_by_id.get(pid) or {}

        points = scoring.score_all_formats(position, player_stats) if player_stats else dict(zeros)
        proj_points = _proj_points(proj)

        if all(v <= 0 for v in points.values()) and all(v <= 0 for v in proj_points.values()):
            continue

        gp = player_stats.get("gp") or 0
        ppg = {fmt: round(pts / gp, 2) if gp else 0.0 for fmt, pts in points.items()}

        records.append(
            {
                "id": pid,
                "name": _display_name(pid, info),
                "position": position,
                "team": info.get("team") or "FA",
                "age": info.get("age"),
                "years_exp": info.get("years_exp"),
                "rookie": not player_stats and (info.get("years_exp") or 0) == 0,
                "injury_status": info.get("injury_status"),
                "status": info.get("status"),
                "market_rank": _market_rank(info),
                "games_played": gp,
                "points": points,
                "points_per_game": ppg,
                "proj_points": proj_points,
                "sleeper_adp": _sleeper_adp(proj),
                "sleeper_dynasty_adp": _sleeper_dynasty_adp(proj),
                "bye": None,  # filled from ADP feed below when available
            }
        )

    # Bye weeks: FFC's ADP feed carries them; spread each player's bye to
    # everyone on the same NFL team so the whole dataset gets covered.
    try:
        from app.services import adp_client
        team_byes: dict[str, int] = {}
        for entry in await adp_client.fetch_entries("ppr"):
            if entry.get("bye") and entry.get("team"):
                team_byes[entry["team"]] = int(entry["bye"])
        for rec in records:
            rec["bye"] = team_byes.get(rec["team"])
    except Exception:
        pass

    _attach_ranks_and_value(records, points_key="points", rank_key="rank_overall",
                            pos_rank_key="rank_position", vbd_key="vbd")
    _attach_ranks_and_value(records, points_key="proj_points", rank_key="proj_rank_overall",
                            pos_rank_key="proj_rank_position", vbd_key="proj_vbd")

    records.sort(key=lambda r: r["proj_points"]["ppr"], reverse=True)
    _cache["players"] = records
    _cache["season"] = season
    _cache["proj_season"] = proj_season
    _cache["built_at"] = time.time()
    return records


def _attach_ranks_and_value(records: list[dict], points_key: str, rank_key: str,
                            pos_rank_key: str, vbd_key: str) -> None:
    for fmt in scoring.SCORING_FORMATS:
        ordered = sorted(records, key=lambda r: r[points_key][fmt], reverse=True)
        for i, rec in enumerate(ordered, start=1):
            rec.setdefault(rank_key, {})[fmt] = i

        by_position: dict[str, list[dict]] = {}
        for rec in ordered:
            by_position.setdefault(rec["position"], []).append(rec)

        for position, pos_records in by_position.items():
            baseline_idx = min(BASELINE_RANK.get(position, 12), len(pos_records)) - 1
            replacement_points = pos_records[baseline_idx][points_key][fmt] if pos_records else 0.0
            for i, rec in enumerate(pos_records, start=1):
                rec.setdefault(pos_rank_key, {})[fmt] = i
                rec.setdefault(vbd_key, {})[fmt] = round(rec[points_key][fmt] - replacement_points, 2)


def season_in_use() -> str | None:
    return _cache["season"]


def projection_season_in_use() -> str | None:
    return _cache["proj_season"]
