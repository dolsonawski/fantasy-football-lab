"""Rankings comparison built on draft-ranking sets.

The comparison table is ordered by the *active draft board* (a computed
VBD board per scoring format, or an imported expert ranking set). For each
player we expose draft rank, computed performance rank, Sleeper market
rank, and the deltas between them — the deltas are where values live.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile

from app.deps import current_user
from app.services import dataset, rankings_import, rankings_store, scoring

router = APIRouter(prefix="/api/rankings", tags=["rankings"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.get("/sets")
async def list_ranking_sets(x_ffl_uid: str | None = Header(default=None)):
    # Soft auth: unauthenticated callers still get built-in + ownerless sets,
    # so tools without the header don't 400. A valid uid additionally filters
    # imported sets to that owner.
    return {"sets": await rankings_store.list_sets(x_ffl_uid)}


@router.delete("/sets/{set_id}")
async def delete_ranking_set(set_id: str, user: dict = Depends(current_user)):
    if not rankings_store.delete_imported_set(set_id, user["id"]):
        raise HTTPException(404, "imported set not found")
    return {"deleted": set_id}


@router.post("/ecr")
async def upload_ecr(file: UploadFile = File(...)):
    """Replace the app's ECR reference board with a FantasyPros export."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "file too large (10 MB max)")
    try:
        result = await rankings_import.parse_and_match(file.filename or "ecr", content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(result["matched"]) < 50:
        raise HTTPException(400, "That file matched fewer than 50 players — is it really a full ECR export?")
    rankings_store.save_ecr(result["matched"], file.filename or "")
    return {
        "matched_count": len(result["matched"]),
        "unmatched": result["unmatched"][:50],
        "unmatched_count": len(result["unmatched"]),
    }


@router.post("/import")
async def import_rankings(file: UploadFile = File(...), name: str = Form(default=""),
                          user: dict = Depends(current_user)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "file too large (10 MB max)")
    try:
        result = await rankings_import.parse_and_match(file.filename or "upload", content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    set_name = name.strip() or (file.filename or "Imported rankings")
    set_id = rankings_store.save_imported_set(set_name, result["matched"], file.filename or "", user["id"])
    return {
        "set_id": set_id,
        "name": set_name,
        "matched_count": len(result["matched"]),
        "unmatched": result["unmatched"][:50],
        "unmatched_count": len(result["unmatched"]),
    }


async def _resolve_ranks(set_id: str) -> dict[str, int]:
    return await rankings_store.get_ranks(set_id)


def _position_ranks(ranked_ids: list[str], by_id: dict[str, dict],
                    entries_by_id: dict[str, dict]) -> dict[str, str]:
    """Board-relative positional rank ('RB1', 'WR12') keyed by player id."""
    counters: dict[str, int] = {}
    out: dict[str, str] = {}
    for pid in ranked_ids:
        rec = by_id.get(pid) or entries_by_id.get(pid)
        pos = (rec or {}).get("position") or "?"
        counters[pos] = counters.get(pos, 0) + 1
        out[pid] = f"{pos}{counters[pos]}"
    return out


@router.get("/compare")
async def compare_rankings(
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    set: str | None = Query(default=None, description="board A (row order); defaults to FFC ADP"),
    compare: str | None = Query(default=None, description="board B to compare against; defaults to Sleeper ADP"),
    position: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
):
    set_a = set or rankings_store.preferred_set_for_format(format)
    set_b = compare or rankings_store.preferred_compare_set_for_format(format)

    try:
        ranks_a = await _resolve_ranks(set_a)
    except KeyError:
        raise HTTPException(404, f"ranking set {set_a} not found")
    except Exception:
        if set is None:  # default FFC ADP unreachable -> projections board
            set_a = f"proj_{format}"
            ranks_a = await _resolve_ranks(set_a)
        else:
            raise HTTPException(502, "ranking source unavailable")

    try:
        ranks_b = await _resolve_ranks(set_b)
    except KeyError:
        raise HTTPException(404, f"ranking set {set_b} not found")
    except Exception:
        raise HTTPException(502, "comparison ranking source unavailable")

    players = await dataset.build_dataset()
    by_id = {p["id"]: p for p in players}

    # FFC ADP / imported sets carry their own entries (names, ADP values),
    # letting us include ranked players missing from the dataset entirely.
    entries_by_id: dict[str, dict] = {}
    try:
        entries = await rankings_store.get_set_entries(set_a)
        if entries:
            entries_by_id = {e["player_id"]: e for e in entries}
    except Exception:
        entries_by_id = {}

    ranked_ids_a = [pid for pid, _ in sorted(ranks_a.items(), key=lambda kv: kv[1])]
    pos_ranks = _position_ranks(ranked_ids_a, by_id, entries_by_id)

    def adp_value(p: dict | None, entry: dict) -> float | None:
        if entry.get("adp") is not None:
            return entry["adp"]
        if p is not None and set_a.startswith("sleeper_adp_"):
            return p["sleeper_adp"].get(format)
        return None

    def value_score(rank_a: int | None, rank_b: int | None) -> float | None:
        """Relative mis-rank, weighted so top-of-board gaps dominate:
        (rank_a - rank_b) / rank_b. Positive = board A ranks the player
        worse than board B says he's worth — a value when drafting on A.
        (Rank 18 vs 10 -> +0.80; rank 250 vs 237 -> +0.05.)"""
        if rank_a is None or rank_b is None:
            return None
        return round((rank_a - rank_b) / rank_b, 2)

    rows = []
    for p in players:
        rank_a = ranks_a.get(p["id"])
        rank_b = ranks_b.get(p["id"])
        entry = entries_by_id.get(p["id"], {})
        rows.append(
            {
                **p,
                "rank_a": rank_a,
                "rank_b": rank_b,
                "pos_rank": pos_ranks.get(p["id"]),
                "adp": adp_value(p, entry),
                "delta": (rank_b - rank_a) if rank_a is not None and rank_b is not None else None,
                "value_score": value_score(rank_a, rank_b),
                "perf_rank": p["rank_overall"][format] if any(v > 0 for v in p["points"].values()) else None,
            }
        )

    for pid, entry in entries_by_id.items():
        if pid not in by_id:
            rank_a = ranks_a.get(pid)
            rank_b = ranks_b.get(pid)
            rows.append(
                {
                    "id": pid,
                    "name": entry["name"],
                    "position": entry.get("position") or "?",
                    "team": entry.get("team") or "?",
                    "points": {f: None for f in scoring.SCORING_FORMATS},
                    "proj_points": {f: None for f in scoring.SCORING_FORMATS},
                    "rank_a": rank_a,
                    "rank_b": rank_b,
                    "pos_rank": pos_ranks.get(pid),
                    "adp": entry.get("adp"),
                    "delta": (rank_b - rank_a) if rank_a is not None and rank_b is not None else None,
                    "value_score": value_score(rank_a, rank_b),
                    "perf_rank": None,
                    "market_rank": None,
                    "rookie": True,
                }
            )

    if position:
        wanted = {p.strip().upper() for p in position.split(",")}
        rows = [r for r in rows if r["position"] in wanted]

    rows.sort(key=lambda r: (r["rank_a"] is None, r["rank_a"] or 0))

    return {
        "season": dataset.season_in_use(),
        "projection_season": dataset.projection_season_in_use(),
        "format": format,
        "set": set_a,
        "compare": set_b,
        "count": len(rows),
        "players": rows[:limit],
    }


@router.get("/formats")
async def list_formats():
    return {"formats": list(scoring.SCORING_FORMATS)}
