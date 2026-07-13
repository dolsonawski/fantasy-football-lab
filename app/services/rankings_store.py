"""Ranking sets: the draft boards everything else runs on.

Three kinds of sets:
- ADP sets ("adp_standard" / "adp_half_ppr" / "adp_ppr"): live preseason
  ADP from real mock drafts (Fantasy Football Calculator). The default
  draft board.
- Computed sets ("computed_*"): players ordered by last season's VBD
  (value over positional replacement) — a production-value reference
  board, useful for spotting where ADP disagrees with actual output.
- Imported sets: user-uploaded expert rankings (CSV/Excel/PDF), persisted
  to disk, matched to Sleeper player ids by normalized name.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from app.services import adp_client, dataset, espn_client, names

# Re-exported for the import parser.
normalize_name = names.normalize_name
match_defense = names.match_defense
TEAM_DEFENSES = names.TEAM_DEFENSES

from app.paths import DATA_DIR as _DATA_ROOT

DATA_DIR = _DATA_ROOT / "rankings"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Expert Consensus Rankings — the reference board the whole app compares
# against (FantasyPros export, refreshed via upload). Kept outside the
# imported-sets folder so it survives set deletions and has a stable id.
ECR_FILE = _DATA_ROOT / "ecr.json"
ECR_SET_ID = "ecr"

ADP_SETS = {
    "adp_standard": ("FFC ADP (Standard)", "standard"),
    "adp_half_ppr": ("FFC ADP (Half-PPR)", "half_ppr"),
    "adp_ppr": ("FFC ADP (PPR)", "ppr"),
}

ESPN_RANK_SETS = {
    "espn_rank_standard": ("ESPN Rankings (Standard)", "standard"),
    "espn_rank_half_ppr": ("ESPN Rankings (Half-PPR)", "half_ppr"),
    "espn_rank_ppr": ("ESPN Rankings (PPR)", "ppr"),
}

ESPN_ADP_SETS = {
    "espn_adp_standard": ("ESPN ADP (Standard)", "standard"),
    "espn_adp_half_ppr": ("ESPN ADP (Half-PPR)", "half_ppr"),
    "espn_adp_ppr": ("ESPN ADP (PPR)", "ppr"),
}

SLEEPER_ADP_SETS = {
    "sleeper_adp_standard": ("Sleeper ADP (Standard)", "standard"),
    "sleeper_adp_half_ppr": ("Sleeper ADP (Half-PPR)", "half_ppr"),
    "sleeper_adp_ppr": ("Sleeper ADP (PPR)", "ppr"),
}

DYNASTY_SETS = {
    "sleeper_dynasty_standard": ("Sleeper Dynasty ADP (Standard)", "standard"),
    "sleeper_dynasty_half_ppr": ("Sleeper Dynasty ADP (Half-PPR)", "half_ppr"),
    "sleeper_dynasty_ppr": ("Sleeper Dynasty ADP (PPR)", "ppr"),
}

PROJECTION_SETS = {
    "proj_standard": ("Projected Points (Standard)", "standard"),
    "proj_half_ppr": ("Projected Points (Half-PPR)", "half_ppr"),
    "proj_ppr": ("Projected Points (PPR)", "ppr"),
}

COMPUTED_SETS = {
    "computed_standard": ("Last-Season Production (Standard)", "standard"),
    "computed_half_ppr": ("Last-Season Production (Half-PPR)", "half_ppr"),
    "computed_ppr": ("Last-Season Production (PPR)", "ppr"),
}


async def build_name_index() -> dict[str, list[dict]]:
    """normalized name -> list of dataset player records (collisions kept)."""
    players = await dataset.build_dataset()
    index: dict[str, list[dict]] = {}
    for p in players:
        index.setdefault(normalize_name(p["name"]), []).append(p)
    return index


def ecr_available() -> bool:
    return ECR_FILE.exists()


def save_ecr(entries: list[dict], source_file: str) -> None:
    payload = {"name": "FantasyPros ECR", "source_file": source_file,
               "updated_at": int(time.time()), "ranks": entries}
    ECR_FILE.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _load_ecr() -> dict:
    return json.loads(ECR_FILE.read_text(encoding="utf-8"))


async def list_sets() -> list[dict]:
    sets = []
    if ecr_available():
        meta = _load_ecr()
        sets.append(
            {
                "id": ECR_SET_ID,
                "name": "FantasyPros ECR",
                "source": "ecr",
                "format": None,
                "player_count": len(meta.get("ranks", [])),
                "updated_at": meta.get("updated_at"),
            }
        )
    sets += [
        {"id": sid, "name": name, "source": "adp", "format": fmt}
        for sid, (name, fmt) in ADP_SETS.items()
    ]
    sets += [
        {"id": sid, "name": name, "source": "espn_rank", "format": fmt}
        for sid, (name, fmt) in ESPN_RANK_SETS.items()
    ]
    sets += [
        {"id": sid, "name": name, "source": "espn_adp", "format": fmt}
        for sid, (name, fmt) in ESPN_ADP_SETS.items()
    ]
    sets += [
        {"id": sid, "name": name, "source": "sleeper_adp", "format": fmt}
        for sid, (name, fmt) in SLEEPER_ADP_SETS.items()
    ]
    sets += [
        {"id": sid, "name": name, "source": "dynasty", "format": fmt}
        for sid, (name, fmt) in DYNASTY_SETS.items()
    ]
    sets += [
        {"id": sid, "name": name, "source": "projections", "format": fmt}
        for sid, (name, fmt) in PROJECTION_SETS.items()
    ]
    sets += [
        {"id": sid, "name": name, "source": "computed", "format": fmt}
        for sid, (name, fmt) in COMPUTED_SETS.items()
    ]
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            sets.append(
                {
                    "id": meta["id"],
                    "name": meta["name"],
                    "source": "imported",
                    "format": meta.get("format"),
                    "player_count": len(meta.get("ranks", [])),
                    "created_at": meta.get("created_at"),
                }
            )
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return sets


async def get_ranks(set_id: str) -> dict[str, int]:
    """Returns {player_id: draft_rank} for the given set."""
    if set_id == ECR_SET_ID:
        if not ecr_available():
            raise KeyError("ECR not loaded — upload a FantasyPros export first")
        return {e["player_id"]: e["rank"] for e in _load_ecr()["ranks"]}

    if set_id in ADP_SETS:
        fmt = ADP_SETS[set_id][1]
        entries = await adp_client.fetch_entries(fmt)
        return {e["player_id"]: e["rank"] for e in entries}

    if set_id in ESPN_RANK_SETS:
        entries = await espn_client.fetch_rank_entries(ESPN_RANK_SETS[set_id][1])
        return {e["player_id"]: e["rank"] for e in entries}

    if set_id in ESPN_ADP_SETS:
        entries = await espn_client.fetch_adp_entries(ESPN_ADP_SETS[set_id][1])
        return {e["player_id"]: e["rank"] for e in entries}

    if set_id in SLEEPER_ADP_SETS:
        fmt = SLEEPER_ADP_SETS[set_id][1]
        players = await dataset.build_dataset()
        ranked = [p for p in players if p["sleeper_adp"].get(fmt) is not None]
        ranked.sort(key=lambda p: p["sleeper_adp"][fmt])
        return {p["id"]: i + 1 for i, p in enumerate(ranked)}

    if set_id in DYNASTY_SETS:
        fmt = DYNASTY_SETS[set_id][1]
        players = await dataset.build_dataset()
        ranked = [p for p in players if (p.get("sleeper_dynasty_adp") or {}).get(fmt) is not None]
        ranked.sort(key=lambda p: p["sleeper_dynasty_adp"][fmt])
        return {p["id"]: i + 1 for i, p in enumerate(ranked)}

    if set_id in PROJECTION_SETS:
        fmt = PROJECTION_SETS[set_id][1]
        players = await dataset.build_dataset()
        ordered = sorted(players, key=lambda p: p["proj_vbd"][fmt], reverse=True)
        return {p["id"]: i + 1 for i, p in enumerate(ordered)}

    if set_id in COMPUTED_SETS:
        fmt = COMPUTED_SETS[set_id][1]
        players = await dataset.build_dataset()
        ordered = sorted(players, key=lambda p: p["vbd"][fmt], reverse=True)
        return {p["id"]: i + 1 for i, p in enumerate(ordered)}

    path = DATA_DIR / f"{set_id}.json"
    if not path.exists():
        raise KeyError(f"ranking set {set_id} not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["player_id"]: entry["rank"] for entry in data["ranks"]}


async def get_set_entries(set_id: str) -> list[dict] | None:
    """Full entries (with names/positions where stored) for sets that carry
    their own player metadata — FFC ADP and imported sets. None for sets
    derived from the dataset itself."""
    if set_id == ECR_SET_ID:
        if not ecr_available():
            raise KeyError("ECR not loaded")
        return _load_ecr()["ranks"]
    if set_id in ADP_SETS:
        return await adp_client.fetch_entries(ADP_SETS[set_id][1])
    if set_id in ESPN_RANK_SETS:
        return await espn_client.fetch_rank_entries(ESPN_RANK_SETS[set_id][1])
    if set_id in ESPN_ADP_SETS:
        return await espn_client.fetch_adp_entries(ESPN_ADP_SETS[set_id][1])
    if (set_id in SLEEPER_ADP_SETS or set_id in DYNASTY_SETS
            or set_id in PROJECTION_SETS or set_id in COMPUTED_SETS):
        return None
    path = DATA_DIR / f"{set_id}.json"
    if not path.exists():
        raise KeyError(f"ranking set {set_id} not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["ranks"]


def save_imported_set(name: str, entries: list[dict], source_file: str) -> str:
    """entries: [{player_id, rank, name}] already matched/deduped."""
    set_id = "imp_" + uuid.uuid4().hex[:8]
    payload = {
        "id": set_id,
        "name": name,
        "source_file": source_file,
        "created_at": int(time.time()),
        "ranks": entries,
    }
    (DATA_DIR / f"{set_id}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return set_id


def delete_imported_set(set_id: str) -> bool:
    path = DATA_DIR / f"{set_id}.json"
    if set_id.startswith("imp_") and path.exists():
        path.unlink()
        return True
    return False


def preferred_set_for_format(fmt: str) -> str:
    """Live FFC ADP is the preferred default board."""
    return f"adp_{fmt}"


def preferred_compare_set_for_format(fmt: str) -> str:
    """ECR is the reference of record when loaded; projections otherwise."""
    return ECR_SET_ID if ecr_available() else f"proj_{fmt}"


async def reference_ranks(fmt: str) -> dict[str, int]:
    """The consensus reference board used for draft-room values and slip
    analysis: FantasyPros ECR when loaded, projections board otherwise."""
    return await get_ranks(preferred_compare_set_for_format(fmt))


def default_set_for_format(fmt: str) -> str:
    """Offline fallback when the ADP provider is unreachable."""
    return f"computed_{fmt}"
