"""Roster/team analysis: grades a set of players as a fantasy roster.

Works on a manually supplied list of player IDs, or a roster pulled live
from a real Sleeper league via league_id + roster_id.
"""
from __future__ import annotations

import httpx

from app.services import dataset, roster_rules, sleeper_client

# Heuristic letter-grade thresholds for total starter VBD (value above
# replacement) in the chosen scoring format. Calibrated against real 2025
# data where a strong RB1 alone carries ~150-200 VBD.
_GRADE_THRESHOLDS = [
    (600, "A+"),
    (450, "A"),
    (350, "B+"),
    (250, "B"),
    (150, "C+"),
    (50, "C"),
    (float("-inf"), "D"),
]

# An empty starter slot scores literal zero, which is worse than a
# replacement-level (VBD=0) player would score — so each hole is penalized
# rather than just excluded from the sum.
_MISSING_SLOT_PENALTY = 100


def _grade_for(total_vbd: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if total_vbd >= threshold:
            return grade
    return "D"


def grade_players(players: list[dict], fmt: str, config: dict | None = None) -> dict:
    """Lightweight lineup grade for a set of already-resolved player records.

    Shared by roster analysis and trade analysis (to compare a roster's
    grade before/after a proposed trade).
    """
    lineup = roster_rules.assign_lineup(players, fmt, config) if players else {
        "starters": {}, "bench": [], "overflow": []
    }
    starters = lineup["starters"]
    filled_starters = [p for p in starters.values() if p is not None]
    missing_slots = [slot for slot, p in starters.items() if p is None]
    starter_vbd = round(sum(roster_rules.player_vbd(p, fmt) for p in filled_starters), 2)
    effective_vbd = round(starter_vbd - len(missing_slots) * _MISSING_SLOT_PENALTY, 2)

    return {
        "grade": _grade_for(effective_vbd),
        "starter_vbd": starter_vbd,
        "effective_vbd": effective_vbd,
        "missing_starter_slots": missing_slots,
        "lineup": lineup,
    }


async def analyze_player_ids(player_ids: list[str], fmt: str, config: dict | None = None) -> dict:
    players = await dataset.build_dataset()
    by_id = {p["id"]: p for p in players}

    found = [by_id[pid] for pid in player_ids if pid in by_id]
    missing_ids = [pid for pid in player_ids if pid not in by_id]

    graded = grade_players(found, fmt, config)
    lineup = graded["lineup"]
    starters = lineup["starters"]

    filled_starters = [p for p in starters.values() if p is not None]
    missing_slots = graded["missing_starter_slots"]
    starter_points = round(sum(roster_rules.player_value(p, fmt) for p in filled_starters), 2)
    starter_vbd = graded["starter_vbd"]
    effective_vbd = graded["effective_vbd"]

    position_strength = {}
    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        pos_starters = [p for p in filled_starters if p["position"] == position]
        position_strength[position] = {
            "starters": [p["name"] for p in pos_starters],
            "vbd": round(sum(roster_rules.player_vbd(p, fmt) for p in pos_starters), 2),
            "filled": len(pos_starters) > 0 or position not in roster_rules.starter_slots(config),
        }

    team_counts: dict[str, int] = {}
    for p in found:
        team_counts[p["team"]] = team_counts.get(p["team"], 0) + 1
    bye_risk = [{"team": t, "count": c} for t, c in team_counts.items() if c >= 3 and t != "FA"]

    injury_flags = [
        {"name": p["name"], "position": p["position"], "status": p["injury_status"]}
        for p in found
        if p.get("injury_status")
    ]

    recommendations = []
    for slot in missing_slots:
        base_pos = slot.rstrip("012") if slot not in ("FLEX",) else "RB/WR/TE"
        recommendations.append(f"No starter at {slot} ({base_pos}) — priority add via waivers or trade.")
    if bye_risk:
        teams_str = ", ".join(f"{b['team']} ({b['count']})" for b in bye_risk)
        recommendations.append(f"Bye-week concentration risk: {teams_str} — these players share a bye week.")
    if injury_flags:
        recommendations.append(f"{len(injury_flags)} player(s) carrying an injury designation — monitor availability.")
    if not recommendations:
        recommendations.append("Roster is well-balanced with no glaring starter holes.")

    return {
        "season": dataset.season_in_use(),
        "format": fmt,
        "grade": graded["grade"],
        "starter_points": starter_points,
        "starter_vbd": starter_vbd,
        "effective_vbd": effective_vbd,
        "starters": {slot: (p["name"] if p else None) for slot, p in starters.items()},
        "starter_detail": {slot: p for slot, p in starters.items()},
        "missing_starter_slots": missing_slots,
        "bench": lineup["bench"],
        "overflow": lineup["overflow"],
        "position_strength": position_strength,
        "bye_week_risk": bye_risk,
        "injury_flags": injury_flags,
        "recommendations": recommendations,
        "missing_player_ids": missing_ids,
        "roster_size": len(found),
    }


async def analyze_sleeper_roster(league_id: str, roster_id: int, fmt: str) -> dict:
    try:
        rosters = await sleeper_client.fetch_league_rosters(league_id)
    except httpx.HTTPStatusError:
        raise ValueError(f"Sleeper league {league_id} not found")
    if not rosters:
        raise ValueError(f"Sleeper league {league_id} not found or has no rosters")
    match = next((r for r in rosters if r.get("roster_id") == roster_id), None)
    if match is None:
        raise ValueError(f"roster_id {roster_id} not found in league {league_id}")

    player_ids = match.get("players") or []
    result = await analyze_player_ids(player_ids, fmt)
    result["owner_id"] = match.get("owner_id")
    result["league_id"] = league_id
    result["roster_id"] = roster_id
    return result
