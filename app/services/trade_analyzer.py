"""Trade analysis: compares raw value exchanged and, when full rosters are
supplied, how each side's lineup grade changes before vs. after the trade.
"""
from __future__ import annotations

from app.services import dataset, roster_analyzer, roster_rules

_FAIRNESS_BANDS = [
    (10, "Fair trade"),
    (25, "Slight edge"),
    (50, "Moderate edge"),
    (float("inf"), "Lopsided trade"),
]


def _side_summary(players: list[dict], fmt: str) -> dict:
    return {
        "players": players,
        "points_total": round(sum(roster_rules.player_value(p, fmt) for p in players), 2),
        "vbd_total": round(sum(roster_rules.player_vbd(p, fmt) for p in players), 2),
    }


def _fairness_label(pct: float) -> str:
    for threshold, label in _FAIRNESS_BANDS:
        if pct < threshold:
            return label
    return "Lopsided trade"


def fairness_label(pct: float) -> str:
    """Public wrapper: the fairness band label for a given imbalance percentage."""
    return _fairness_label(pct)


async def analyze_trade(
    team_a_sends_ids: list[str],
    team_b_sends_ids: list[str],
    fmt: str,
    team_a_roster_ids: list[str] | None = None,
    team_b_roster_ids: list[str] | None = None,
) -> dict:
    players = await dataset.build_dataset()
    by_id = {p["id"]: p for p in players}

    def resolve(ids: list[str]) -> tuple[list[dict], list[str]]:
        found = [by_id[pid] for pid in ids if pid in by_id]
        missing = [pid for pid in ids if pid not in by_id]
        return found, missing

    a_sends, a_missing = resolve(team_a_sends_ids)
    b_sends, b_missing = resolve(team_b_sends_ids)

    a_sends_summary = _side_summary(a_sends, fmt)  # value leaving team A
    b_sends_summary = _side_summary(b_sends, fmt)  # value leaving team B (received by A)

    a_net_vbd = round(b_sends_summary["vbd_total"] - a_sends_summary["vbd_total"], 2)
    total_exchanged_vbd = max(
        (abs(a_sends_summary["vbd_total"]) + abs(b_sends_summary["vbd_total"])) / 2, 1.0
    )
    imbalance_pct = round(abs(a_net_vbd) / total_exchanged_vbd * 100, 1)
    label = _fairness_label(imbalance_pct)

    if label == "Fair trade":
        verdict = "Fair trade — both sides give up similar value."
        winner = None
        headline = label
    else:
        winner = "Team A" if a_net_vbd > 0 else "Team B"
        verdict = f"{label} favoring {winner} (~{imbalance_pct}% value imbalance)."
        headline = f"{label} — {winner}"

    result = {
        "season": dataset.season_in_use(),
        "format": fmt,
        "team_a_sends": a_sends,
        "team_b_sends": b_sends,
        "team_a_sends_value": a_sends_summary,
        "team_b_sends_value": b_sends_summary,
        "team_a_net_vbd": a_net_vbd,
        "imbalance_pct": imbalance_pct,
        "verdict": verdict,
        "winner": winner,
        "fair": label == "Fair trade",
        "winner_side": winner,
        "margin_pct": imbalance_pct,
        "verdict_label": label,
        "headline": headline,
        "missing_player_ids": a_missing + b_missing,
    }

    if team_a_roster_ids is not None:
        a_before, _ = resolve(team_a_roster_ids)
        a_sends_ids = {p["id"] for p in a_sends}
        a_after = [p for p in a_before if p["id"] not in a_sends_ids] + b_sends
        result["team_a_roster_impact"] = {
            "before": roster_analyzer.grade_players(a_before, fmt),
            "after": roster_analyzer.grade_players(a_after, fmt),
        }

    if team_b_roster_ids is not None:
        b_before, _ = resolve(team_b_roster_ids)
        b_sends_ids = {p["id"] for p in b_sends}
        b_after = [p for p in b_before if p["id"] not in b_sends_ids] + a_sends
        result["team_b_roster_impact"] = {
            "before": roster_analyzer.grade_players(b_before, fmt),
            "after": roster_analyzer.grade_players(b_after, fmt),
        }

    return result
