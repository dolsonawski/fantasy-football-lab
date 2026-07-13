"""Fantasy scoring formulas applied to real Sleeper season stats.

Sleeper's public API exposes raw play-by-play-derived stat totals per player
(pass_yd, rec, rush_td, etc.) but not proprietary "expert rankings" from any
vendor. We compute our own points/ranks per scoring format from those real
stats, which lets us legitimately compare "systems" (Standard vs Half-PPR vs
PPR) without pretending to reproduce a paid provider's proprietary board.
"""
from __future__ import annotations

SCORING_FORMATS = ("standard", "half_ppr", "ppr")

_RECEPTION_POINTS = {
    "standard": 0.0,
    "half_ppr": 0.5,
    "ppr": 1.0,
}


def _get(stats: dict, key: str) -> float:
    val = stats.get(key)
    return float(val) if isinstance(val, (int, float)) else 0.0


def score_offense(stats: dict, fmt: str) -> float:
    pts = 0.0
    pts += _get(stats, "pass_yd") * 0.04
    pts += _get(stats, "pass_td") * 4.0
    pts += _get(stats, "pass_int") * -2.0
    pts += _get(stats, "pass_2pt") * 2.0

    pts += _get(stats, "rush_yd") * 0.1
    pts += _get(stats, "rush_td") * 6.0
    pts += _get(stats, "rush_2pt") * 2.0

    pts += _get(stats, "rec_yd") * 0.1
    pts += _get(stats, "rec_td") * 6.0
    pts += _get(stats, "rec_2pt") * 2.0
    pts += _get(stats, "rec") * _RECEPTION_POINTS[fmt]

    pts += _get(stats, "fum_lost") * -2.0
    pts += _get(stats, "st_td") * 6.0
    pts += _get(stats, "st_fum_rec") * 2.0
    return round(pts, 2)


def score_kicker(stats: dict, fmt: str) -> float:
    pts = 0.0
    pts += _get(stats, "fgm") * 3.0
    pts += _get(stats, "fgm_50p") * 1.0  # bonus for 50+ yard makes
    pts += _get(stats, "xpm") * 1.0
    pts -= _get(stats, "fgmiss") * 1.0
    pts -= _get(stats, "xpmiss") * 1.0
    return round(pts, 2)


def score_defense(stats: dict, fmt: str) -> float:
    """Standard team-defense scoring using Sleeper's actual DEF stat keys
    (sack/int/fum_rec, not def_*-prefixed), with exact per-week points-
    allowed tier counts that Sleeper provides in season totals."""
    pts = 0.0
    pts += _get(stats, "sack") * 1.0
    pts += _get(stats, "int") * 2.0
    pts += _get(stats, "fum_rec") * 2.0
    pts += _get(stats, "def_td") * 6.0
    pts += _get(stats, "def_st_td") * 6.0
    pts += _get(stats, "safe") * 2.0
    pts += _get(stats, "blk_kick") * 2.0

    # Weekly points-allowed tiers (counts of games in each band).
    pts += _get(stats, "pts_allow_0") * 10.0
    pts += _get(stats, "pts_allow_1_6") * 7.0
    pts += _get(stats, "pts_allow_7_13") * 4.0
    pts += _get(stats, "pts_allow_14_20") * 1.0
    pts += _get(stats, "pts_allow_28_34") * -1.0
    pts += _get(stats, "pts_allow_35p") * -4.0
    return round(pts, 2)


def score_player(position: str, stats: dict, fmt: str) -> float:
    if fmt not in SCORING_FORMATS:
        raise ValueError(f"unknown scoring format: {fmt}")
    if position == "K":
        return score_kicker(stats, fmt)
    if position == "DEF":
        return score_defense(stats, fmt)
    return score_offense(stats, fmt)


def score_all_formats(position: str, stats: dict) -> dict:
    return {fmt: score_player(position, stats, fmt) for fmt in SCORING_FORMATS}
