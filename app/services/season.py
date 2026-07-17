"""Season-long tools built on an imported league: start/sit optimizer
(season-long or a specific week), waiver / free-agent finder, and a
bye-week planner.
"""
from __future__ import annotations

from app.services import dataset, roster_rules, schedule_client, sleeper_client

_WEEKLY_KEYS = {"standard": "pts_std", "half_ppr": "pts_half_ppr", "ppr": "pts_ppr"}


async def _weekly_overlay(players: list[dict], fmt: str, week: int) -> tuple[list[dict], bool]:
    """Returns player copies whose proj_points reflect the given week's
    projections. Second value is False when Sleeper has no data for that
    week yet (caller falls back to season-long)."""
    season_year = dataset.projection_season_in_use() or dataset.PROJECTION_SEASON
    weekly = await sleeper_client.fetch_weekly_projections(str(season_year), week)
    if not weekly:
        return players, False
    key = _WEEKLY_KEYS[fmt]
    out = []
    for p in players:
        w = weekly.get(p["id"]) or {}
        pts = float(w.get(key) or 0.0)
        wk_points = {f: float((weekly.get(p["id"]) or {}).get(k) or 0.0) for f, k in _WEEKLY_KEYS.items()}
        out.append({**p, "proj_points": wk_points, "proj_vbd": {f: v for f, v in wk_points.items()}})
    return out, True


def _by_id(players: list[dict]) -> dict[str, dict]:
    return {p["id"]: p for p in players}


def _team(league: dict, team_id: str) -> dict:
    for t in league["teams"]:
        if t["team_id"] == team_id:
            return t
    raise ValueError("team not found in league")


async def start_sit(league: dict, team_id: str, fmt: str, config: dict | None = None,
                    week: int | None = None) -> dict:
    """Optimal lineup for a team plus sit/bench, injury flags, and close
    calls. With `week`, uses that week's projections (falls back to
    season-long when the week isn't published yet)."""
    players = await dataset.build_dataset()
    by_id = _by_id(players)
    team = _team(league, team_id)
    roster = [by_id[pid] for pid in team["players"] if pid in by_id]

    weekly_used = False
    if week:
        roster, weekly_used = await _weekly_overlay(roster, fmt, week)

    lineup = roster_rules.assign_lineup(roster, fmt, config)
    starters = [
        {"slot": slot, **_slim(p, fmt)}
        for slot, p in lineup["starters"].items() if p is not None
    ]
    empty_slots = [slot for slot, p in lineup["starters"].items() if p is None]
    bench = [_slim(p, fmt) for p in lineup["bench"] + lineup["overflow"]]

    # Weekly opponent chips: only meaningful once a specific week's
    # projections are in play. Best-effort — a schedule-fetch failure just
    # means starters render without an opponent tag.
    if week and weekly_used:
        try:
            for s in starters:
                opp = await schedule_client.team_week_opponent(s.get("team"), week)
                if opp:
                    s["opponent"] = f"{'vs' if opp['home'] else '@'} {opp['opponent']}"
                    s["opponent_difficulty"] = await schedule_client.matchup_difficulty(opp["opponent"])
                else:
                    s["opponent"] = None
                    s["opponent_difficulty"] = None
        except Exception:
            pass

    starter_ids = {s["id"] for s in starters}
    injuries = [
        _slim(p, fmt) | {"injury_status": p.get("injury_status")}
        for p in roster
        if p.get("injury_status") and p["id"] in starter_ids
    ]

    # Close calls: a bench player within 15% of a same-eligibility starter.
    close_calls = []
    for b in lineup["bench"]:
        bval = roster_rules.player_value(b, fmt)
        for slot, s in lineup["starters"].items():
            if s is None:
                continue
            if not _interchangeable(b, s, slot):
                continue
            sval = roster_rules.player_value(s, fmt)
            if sval > 0 and bval >= sval * 0.85 and bval < sval:
                close_calls.append(
                    {
                        "bench": _slim(b, fmt),
                        "starter": _slim(s, fmt),
                        "slot": slot,
                        "gap": round(sval - bval, 1),
                    }
                )
                break
    close_calls.sort(key=lambda c: c["gap"])

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "format": fmt,
        "week": week if weekly_used else None,
        "weekly_available": weekly_used,
        "starters": starters,
        "empty_slots": empty_slots,
        "bench": bench,
        "injuries": injuries,
        "close_calls": close_calls[:6],
    }


async def bye_planner(league: dict, team_id: str, fmt: str) -> dict:
    """Groups a roster by bye week and flags weeks where multiple starters
    sit out at once."""
    players = await dataset.build_dataset()
    by_id = _by_id(players)
    team = _team(league, team_id)
    roster = [by_id[pid] for pid in team["players"] if pid in by_id]

    lineup = roster_rules.assign_lineup(roster, fmt)
    starter_ids = {p["id"] for p in lineup["starters"].values() if p is not None}

    weeks: dict[int, list[dict]] = {}
    unknown: list[dict] = []
    for p in roster:
        entry = _slim(p, fmt) | {"is_starter": p["id"] in starter_ids}
        if p.get("bye"):
            weeks.setdefault(int(p["bye"]), []).append(entry)
        else:
            unknown.append(entry)

    out_weeks = []
    for wk in sorted(weeks):
        group = sorted(weeks[wk], key=lambda e: -e["proj_points"])
        starters_out = sum(1 for e in group if e["is_starter"])
        out_weeks.append({
            "week": wk,
            "players": group,
            "starters_out": starters_out,
            "crunch": starters_out >= 3,
        })

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "format": fmt,
        "weeks": out_weeks,
        "unknown_bye": unknown,
        "worst_week": max(out_weeks, key=lambda w: w["starters_out"])["week"] if out_weeks else None,
    }


async def playoff_outlook(league: dict, team_id: str, fmt: str, config: dict | None = None) -> dict:
    """Fantasy-playoff-week (15-17) outlook for a team's roster: each
    player's team playoff schedule strength (1-5 stars, 5=easiest) plus a
    warning banner for starters facing a tough (1-2 star) playoff slate."""
    players = await dataset.build_dataset()
    by_id = _by_id(players)
    team = _team(league, team_id)
    roster = [by_id[pid] for pid in team["players"] if pid in by_id]

    try:
        sos = await schedule_client.playoff_sos()
    except Exception:
        sos = {}

    lineup = roster_rules.assign_lineup(roster, fmt, config)
    starter_ids = {p["id"] for p in lineup["starters"].values() if p is not None}

    roster_sorted = sorted(roster, key=lambda p: roster_rules.player_value(p, fmt), reverse=True)
    rows = []
    tough_starters = []
    for p in roster_sorted:
        team_sos = sos.get(p.get("team")) if p.get("team") else None
        entry = _slim(p, fmt) | {
            "is_starter": p["id"] in starter_ids,
            "playoff_sos": team_sos,
        }
        rows.append(entry)
        if team_sos and entry["is_starter"] and team_sos["stars"] <= 2:
            tough_starters.append(entry)

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "format": fmt,
        "players": rows,
        "tough_starters": tough_starters,
        "schedule_available": bool(sos),
    }


def _interchangeable(a: dict, b: dict, slot: str) -> bool:
    base = slot.rstrip("0123456789")
    if base == "FLEX":
        return a["position"] in roster_rules.FLEX_ELIGIBLE
    if base == "SUPERFLEX":
        return a["position"] in roster_rules.SUPERFLEX_ELIGIBLE
    return a["position"] == b["position"]


async def waiver_targets(league: dict, team_id: str, fmt: str, config: dict | None = None,
                         limit: int = 12) -> dict:
    """Free agents (unrostered anywhere in the league) ranked overall, plus
    the best adds that would actually upgrade this team's starting lineup."""
    players = await dataset.build_dataset()
    by_id = _by_id(players)
    team = _team(league, team_id)

    rostered = set()
    for t in league["teams"]:
        rostered.update(t["players"])

    free_agents = [
        p for p in players
        if p["id"] not in rostered and roster_rules.player_value(p, fmt) > 0
    ]
    free_agents.sort(key=lambda p: roster_rules.player_value(p, fmt), reverse=True)

    # Overall waiver watch: best players nobody rostered.
    top_available = [_slim(p, fmt) for p in free_agents[:limit]]

    # Best adds for THIS team: simulate adding each top FA and measure the
    # gain in starting-lineup value (captures flex + positional need).
    my_roster = [by_id[pid] for pid in team["players"] if pid in by_id]
    base_vbd = _starter_vbd(my_roster, fmt, config)
    adds = []
    for fa in free_agents[:60]:
        gain = _starter_vbd(my_roster + [fa], fmt, config) - base_vbd
        if gain > 0.5:
            adds.append({**_slim(fa, fmt), "upgrade_vbd": round(gain, 1)})
    adds.sort(key=lambda a: -a["upgrade_vbd"])

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "format": fmt,
        "free_agent_count": len(free_agents),
        "top_available": top_available,
        "best_adds": adds[:limit],
    }


def _starter_vbd(roster: list[dict], fmt: str, config: dict | None) -> float:
    lineup = roster_rules.assign_lineup(roster, fmt, config)
    return sum(
        roster_rules.player_vbd(p, fmt)
        for p in lineup["starters"].values() if p is not None
    )


def _slim(p: dict, fmt: str) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "position": p["position"],
        "team": p.get("team"),
        "proj_points": round(roster_rules.player_value(p, fmt), 1),
        "proj_pos_rank": (p.get("proj_rank_position") or {}).get(fmt),
        "injury_status": p.get("injury_status"),
        "rookie": p.get("rookie"),
    }
