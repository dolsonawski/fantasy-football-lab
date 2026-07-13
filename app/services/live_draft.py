"""Live Sleeper draft assistant.

Point it at a real Sleeper draft ID (from the draft-room URL:
sleeper.com/draft/nfl/<draft_id>) and it polls picks, removes drafted
players from the pool, and surfaces the best remaining values vs the
consensus (ECR) board — the mock room's edge, live on draft day.
Works for any draft you can see, including mocks.
"""
from __future__ import annotations

import httpx

from app.services import dataset, rankings_store, roster_rules, sleeper_client

UNRANKED = 10**6


async def snapshot(draft_id: str, fmt: str) -> dict:
    try:
        meta = await sleeper_client.fetch_draft(draft_id)
        picks = await sleeper_client.fetch_draft_picks(draft_id)
    except httpx.HTTPStatusError:
        raise ValueError(f"Sleeper draft {draft_id} not found — check the ID in your draft-room URL")

    try:
        ref_ranks = await rankings_store.reference_ranks(fmt)
    except Exception:
        ref_ranks = {}

    players = await dataset.build_dataset()
    by_id = {p["id"]: p for p in players}

    taken_ids = {p.get("player_id") for p in picks if p.get("player_id")}
    pick_no = len(picks) + 1

    pick_rows = [
        {
            "pick_no": p.get("pick_no"),
            "round": p.get("round"),
            "player_id": p.get("player_id"),
            "name": f"{(p.get('metadata') or {}).get('first_name', '')} {(p.get('metadata') or {}).get('last_name', '')}".strip(),
            "position": (p.get("metadata") or {}).get("position"),
            "team": (p.get("metadata") or {}).get("team"),
            "picked_by_slot": p.get("draft_slot"),
        }
        for p in picks
    ]

    available = [p for p in players if p["id"] not in taken_ids]

    def ref(pid: str) -> int:
        return ref_ranks.get(pid, UNRANKED)

    available.sort(key=lambda p: ref(p["id"]))

    def slim(p: dict) -> dict:
        r = ref(p["id"])
        return {
            "id": p["id"],
            "name": p["name"],
            "position": p["position"],
            "team": p["team"],
            "ecr": r if r < UNRANKED else None,
            "proj_points": round(roster_rules.player_value(p, fmt), 1),
            "value_fall": (pick_no - r) if r < UNRANKED else None,
        }

    best_available = [slim(p) for p in available[:12]]

    # Steals on the board right now: fallen past consensus, weighted so
    # early-round falls dominate.
    values = []
    for p in available[:250]:
        r = ref(p["id"])
        if r >= UNRANKED:
            continue
        fall = pick_no - r
        if fall > 0:
            values.append((fall / r, slim(p)))
    values.sort(key=lambda x: -x[0])
    best_values = [v for _, v in values[:8]]

    by_position = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        cand = next((p for p in available if p["position"] == pos and ref(p["id"]) < UNRANKED), None)
        if cand:
            by_position.append(slim(cand))

    settings = meta.get("settings") or {}
    return {
        "draft_id": draft_id,
        "status": meta.get("status"),
        "type": meta.get("type"),
        "teams": settings.get("teams"),
        "rounds": settings.get("rounds"),
        "current_pick": pick_no,
        "current_round": ((pick_no - 1) // max(settings.get("teams") or 12, 1)) + 1,
        "picks_made": len(picks),
        "recent_picks": pick_rows[-10:][::-1],
        "best_available": best_available,
        "best_values": best_values,
        "by_position": by_position,
        "reference": "ECR" if ref_ranks else "unavailable",
    }
