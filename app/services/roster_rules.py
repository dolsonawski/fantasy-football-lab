"""Shared roster-construction rules used by the draft simulator, roster
analyzer, trade analyzer, and season tools.

Roster shape is configurable (starters per position + FLEX/SUPERFLEX + bench),
so a draft can run any league format. Everything defaults to the classic
1-QB, 2-RB, 2-WR, 1-TE, 1-FLEX, 1-K, 1-DEF, 6-bench setup.
"""
from __future__ import annotations

from collections import OrderedDict

# Positions that can fill each flex kind.
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SUPERFLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}

BASE_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

DEFAULT_CONFIG = {
    "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPERFLEX": 0, "K": 1, "DEF": 1,
    "BENCH": 6,
}


def normalize_config(config: dict | None) -> dict:
    """Fill in and clamp a roster config to safe ranges."""
    cfg = dict(DEFAULT_CONFIG)
    if config:
        for key in cfg:
            if key in config and isinstance(config[key], (int, float)):
                cfg[key] = max(0, min(int(config[key]), 12))
    # Always need at least one roster spot.
    if sum(cfg.values()) == 0:
        cfg["BENCH"] = 1
    return cfg


def starter_slots(config: dict | None = None) -> "OrderedDict[str, int]":
    """Ordered slot->count map for the starting lineup (excludes BENCH)."""
    cfg = normalize_config(config)
    slots: "OrderedDict[str, int]" = OrderedDict()
    for pos in ("QB", "RB", "WR", "TE", "FLEX", "SUPERFLEX", "K", "DEF"):
        if cfg.get(pos, 0) > 0:
            slots[pos] = cfg[pos]
    return slots


def total_roster_size(config: dict | None = None) -> int:
    cfg = normalize_config(config)
    return sum(cfg.values())


# Legacy module-level constants (standard league) kept for any bare callers.
STARTER_SLOTS = starter_slots(None)
BENCH_SIZE = DEFAULT_CONFIG["BENCH"]
TOTAL_ROSTER_SIZE = total_roster_size(None)


def position_counts(players: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in players:
        counts[p["position"]] = counts.get(p["position"], 0) + 1
    return counts


def player_value(p: dict, fmt: str) -> float:
    """Projected points for the upcoming season (falls back to last season's
    production for players without a projection)."""
    proj = p.get("proj_points", {}).get(fmt, 0.0)
    return proj if proj > 0 else p.get("points", {}).get(fmt, 0.0)


def player_vbd(p: dict, fmt: str) -> float:
    proj = p.get("proj_points", {}).get(fmt, 0.0)
    if proj > 0 and "proj_vbd" in p:
        return p["proj_vbd"][fmt]
    return p.get("vbd", {}).get(fmt, 0.0)


def _slot_keys(config: dict | None = None) -> list[str]:
    """Concrete slot labels, e.g. RB1, RB2, WR1, FLEX, SUPERFLEX."""
    keys: list[str] = []
    for slot, count in starter_slots(config).items():
        if count == 1:
            keys.append(slot)
        else:
            keys.extend(f"{slot}{i + 1}" for i in range(count))
    return keys


def assign_lineup(players: list[dict], fmt: str, config: dict | None = None) -> dict:
    """Greedily assigns players to starter slots by projected points, rest to
    bench.

    Returns {"starters": {slot: player|None}, "bench": [player], "overflow": [player]}
    """
    cfg = normalize_config(config)
    remaining = sorted(players, key=lambda p: player_value(p, fmt), reverse=True)
    starters: "dict[str, dict | None]" = {}

    def take(eligible) -> dict | None:
        pick = next((p for p in remaining if p["position"] in eligible), None)
        if pick:
            remaining.remove(pick)
        return pick

    # Dedicated position slots first, then FLEX, then SUPERFLEX.
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        count = cfg.get(pos, 0)
        for i in range(count):
            key = pos if count == 1 else f"{pos}{i + 1}"
            starters[key] = take({pos})
    for i in range(cfg.get("FLEX", 0)):
        key = "FLEX" if cfg["FLEX"] == 1 else f"FLEX{i + 1}"
        starters[key] = take(FLEX_ELIGIBLE)
    for i in range(cfg.get("SUPERFLEX", 0)):
        key = "SUPERFLEX" if cfg["SUPERFLEX"] == 1 else f"SUPERFLEX{i + 1}"
        starters[key] = take(SUPERFLEX_ELIGIBLE)

    bench_size = cfg.get("BENCH", 0)
    bench = remaining[:bench_size]
    overflow = remaining[bench_size:]
    return {"starters": starters, "bench": bench, "overflow": overflow}


def starter_gap(counts: dict[str, int], position: str, config: dict | None = None) -> int:
    """How many more starters are needed at this position (can be negative).

    Counts FLEX/SUPERFLEX demand toward eligible positions so a flex-heavy
    league still values RB/WR/TE depth."""
    cfg = normalize_config(config)
    dedicated = cfg.get(position, 0)
    flex_share = 0.0
    if position in FLEX_ELIGIBLE:
        flex_share += cfg.get("FLEX", 0) / max(len(FLEX_ELIGIBLE), 1)
    if position in SUPERFLEX_ELIGIBLE:
        flex_share += cfg.get("SUPERFLEX", 0) / max(len(SUPERFLEX_ELIGIBLE), 1)
    demand = dedicated + flex_share
    return int(round(demand)) - counts.get(position, 0)


def target_depth(position: str, config: dict | None = None) -> int:
    """How many startable bodies a competitive roster wants at a position
    (starters + a reasonable flex/bench cushion). Used by trade/waiver logic."""
    cfg = normalize_config(config)
    base = cfg.get(position, 0)
    if position in FLEX_ELIGIBLE:
        base += cfg.get("FLEX", 0)
    if position in SUPERFLEX_ELIGIBLE:
        base += cfg.get("SUPERFLEX", 0)
    cushion = {"RB": 2, "WR": 2, "QB": 1, "TE": 1}.get(position, 0)
    return base + cushion
