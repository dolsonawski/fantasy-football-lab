"""Finds complementary trade partners within an imported league.

A good trade partner is one whose roster shape mirrors yours: they're deep
(surplus) where you're thin (need), and thin where you're deep. We compute
each team's per-position surplus/need from projected value, pair teams whose
shapes complement, and build a concrete value-matched swap for each pairing,
scored by the existing trade analyzer.
"""
from __future__ import annotations

from app.services import dataset, roster_rules, trade_analyzer

# How many startable bodies a competitive roster wants at each position
# (starter slots + reasonable flex/bench depth). Anything beyond this that's
# still startable is tradeable surplus. Derived from the standard roster.
_TARGET_DEPTH = {pos: roster_rules.target_depth(pos) for pos in ("QB", "RB", "WR", "TE")}
_STARTABLE_VBD = -20.0  # projected VBD floor to count as a real asset


def _startable(p: dict, fmt: str) -> bool:
    return roster_rules.player_vbd(p, fmt) >= _STARTABLE_VBD


def team_profile(players: list[dict], fmt: str) -> dict:
    """Per-position surplus (tradeable extras) and need (thin spots)."""
    by_pos: dict[str, list[dict]] = {}
    for p in players:
        by_pos.setdefault(p["position"], []).append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: roster_rules.player_vbd(p, fmt), reverse=True)

    surplus: dict[str, list[dict]] = {}
    need: dict[str, float] = {}
    for pos, target in _TARGET_DEPTH.items():
        pool = by_pos.get(pos, [])
        startable = [p for p in pool if _startable(p, fmt)]
        # Surplus = startable depth beyond the target (weakest first stays,
        # the extras beyond target are what you'd deal).
        if len(startable) > target:
            surplus[pos] = startable[target:]
        # Need severity: how far below target you are, scaled by how weak the
        # best option is (empty/very thin positions score highest).
        shortfall = max(0, target - len(startable))
        best_vbd = roster_rules.player_vbd(pool[0], fmt) if pool else -100.0
        need[pos] = round(shortfall * 20 + max(0.0, 20 - best_vbd) * 0.5, 1)

    return {"surplus": surplus, "need": need}


def _best_surplus_for(profile: dict, pos: str, fmt: str) -> dict | None:
    extras = profile["surplus"].get(pos) or []
    # Deal from the top of your surplus (most enticing to a partner).
    return extras[0] if extras else None


async def find_matches(league: dict, my_team_id: str, fmt: str, limit: int = 4) -> dict:
    players = await dataset.build_dataset()
    by_id = {p["id"]: p for p in players}

    def roster(team: dict) -> list[dict]:
        return [by_id[pid] for pid in team["players"] if pid in by_id]

    teams = {t["team_id"]: t for t in league["teams"]}
    if my_team_id not in teams:
        raise ValueError("team not found in league")

    my_team = teams[my_team_id]
    my_players = roster(my_team)
    my_profile = team_profile(my_players, fmt)

    proposals = []
    for tid, team in teams.items():
        if tid == my_team_id:
            continue
        their_players = roster(team)
        their_profile = team_profile(their_players, fmt)

        # I send from a position where I'm deep and they're thin; I receive
        # from a position where they're deep and I'm thin.
        send_pos = max(
            (pos for pos in my_profile["surplus"] if their_profile["need"].get(pos, 0) > 15),
            key=lambda pos: their_profile["need"][pos],
            default=None,
        )
        recv_pos = max(
            (pos for pos in their_profile["surplus"] if my_profile["need"].get(pos, 0) > 15),
            key=lambda pos: my_profile["need"][pos],
            default=None,
        )
        if not send_pos or not recv_pos or send_pos == recv_pos:
            continue

        i_send = _best_surplus_for(my_profile, send_pos, fmt)
        i_recv = _best_surplus_for(their_profile, recv_pos, fmt)
        if not i_send or not i_recv:
            continue

        analysis = await trade_analyzer.analyze_trade(
            [i_send["id"]], [i_recv["id"]], fmt,
            team_a_roster_ids=[p["id"] for p in my_players],
            team_b_roster_ids=[p["id"] for p in their_players],
        )
        # Complementarity score: how well each side scratches the other's itch.
        fit = their_profile["need"][send_pos] + my_profile["need"][recv_pos]
        # Prefer trades that aren't lopsidedly against me.
        balance_penalty = analysis["imbalance_pct"] if analysis.get("winner") == "Team B" else 0
        score = round(fit - balance_penalty, 1)

        proposals.append(
            {
                "partner_team_id": tid,
                "partner_team_name": team["name"],
                "you_send": {"position": send_pos, "player": i_send},
                "you_receive": {"position": recv_pos, "player": i_recv},
                "rationale": (
                    f"You're deep at {send_pos} and thin at {recv_pos}; "
                    f"{team['name']} is the mirror image."
                ),
                "verdict": analysis["verdict"],
                "winner": analysis["winner"],
                "winner_side": analysis["winner"],
                "verdict_label": trade_analyzer.fairness_label(analysis["imbalance_pct"]),
                "imbalance_pct": analysis["imbalance_pct"],
                "your_grade_before": analysis.get("team_a_roster_impact", {}).get("before", {}).get("grade"),
                "your_grade_after": analysis.get("team_a_roster_impact", {}).get("after", {}).get("grade"),
                "score": score,
            }
        )

    proposals.sort(key=lambda p: -p["score"])
    return {
        "format": fmt,
        "my_team_id": my_team_id,
        "my_team_name": my_team["name"],
        "my_needs": {k: v for k, v in sorted(my_profile["need"].items(), key=lambda kv: -kv[1]) if v > 15},
        "my_surplus": {pos: [pl["name"] for pl in extras] for pos, extras in my_profile["surplus"].items()},
        "proposals": proposals[:limit],
    }
