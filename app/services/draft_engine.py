"""In-memory snake mock draft simulator built on draft-ranking boards.

The draft board order comes from a ranking set (computed VBD board per
scoring format, or an imported expert set) snapshotted at draft creation.
AI opponents draft by board rank scaled by positional need, with weighted
randomness among the top candidates so repeated mocks vary realistically.

Also provides pick suggestions (best available / best board value / best
roster fit) and full post-draft grading (league comparison, positional
strengths/weaknesses, and per-pick "slip" analysis).
"""
from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path
from typing import Optional

from app.services import dataset, rankings_store, roster_analyzer, roster_rules

from app.paths import DATA_DIR

_drafts: dict[str, dict] = {}

_USERS_DIR = DATA_DIR / "users"


def _history_dir(user_id: str) -> Path:
    d = _USERS_DIR / user_id / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d

MAX_TEAMS = 16
MIN_TEAMS = 4
UNRANKED = 10**6
SLIP_RANK_THRESHOLD = 10  # picked this many board spots below best need-filling alternative


def _build_snake_order(teams: int, rounds: int) -> list[int]:
    order: list[int] = []
    for rnd in range(1, rounds + 1):
        seq = list(range(1, teams + 1)) if rnd % 2 == 1 else list(range(teams, 0, -1))
        order.extend(seq)
    return order


def _synthetic_record(entry: dict) -> dict:
    """A draftable record for a ranked player with no stats yet (rookies).

    Zeroed stats keep lineup/grading math working; their draft value comes
    entirely from board rank.
    """
    zeros = {fmt: 0.0 for fmt in ("standard", "half_ppr", "ppr")}
    return {
        "id": entry["player_id"],
        "name": entry["name"],
        "position": entry.get("position") or "?",
        "team": entry.get("team") or "FA",
        "age": None,
        "years_exp": 0,
        "injury_status": None,
        "status": "Active",
        "market_rank": None,
        "games_played": 0,
        "points": dict(zeros),
        "points_per_game": dict(zeros),
        "vbd": dict(zeros),
        "proj_points": dict(zeros),
        "proj_vbd": dict(zeros),
        "sleeper_adp": {fmt: None for fmt in zeros},
        "rank_overall": {fmt: None for fmt in zeros},
        "rank_position": {fmt: None for fmt in zeros},
        "rookie": True,
    }


async def create_draft(
    teams: int,
    user_slot: int,
    fmt: str,
    rounds: Optional[int] = None,
    ranking_set: Optional[str] = None,
    owner_id: Optional[str] = None,
    roster_config: Optional[dict] = None,
) -> dict:
    if not (MIN_TEAMS <= teams <= MAX_TEAMS):
        raise ValueError(f"teams must be between {MIN_TEAMS} and {MAX_TEAMS}")
    if not (1 <= user_slot <= teams):
        raise ValueError("user_slot must be within 1..teams")
    config = roster_rules.normalize_config(roster_config)
    rounds = rounds or roster_rules.total_roster_size(config)

    set_id = ranking_set or rankings_store.preferred_set_for_format(fmt)
    entries = None
    try:
        ranks = await rankings_store.get_ranks(set_id)
        entries = await rankings_store.get_set_entries(set_id)
    except KeyError:
        raise ValueError(f"ranking set {set_id} not found")
    except Exception:
        if ranking_set is None:  # ADP provider down -> computed fallback
            set_id = rankings_store.default_set_for_format(fmt)
            ranks = await rankings_store.get_ranks(set_id)
        else:
            raise ValueError("ranking source unavailable")

    # Consensus reference (ECR when loaded) — drives value suggestions and
    # post-draft slip analysis, independent of the room's draft board.
    try:
        ref_ranks = await rankings_store.reference_ranks(fmt)
    except Exception:
        ref_ranks = dict(ranks)

    players = await dataset.build_dataset()
    known_ids = {p["id"] for p in players}
    extras = {}
    if entries:
        for entry in entries:
            if entry["player_id"] not in known_ids:
                extras[entry["player_id"]] = _synthetic_record(entry)

    draft_id = uuid.uuid4().hex[:12]
    draft = {
        "id": draft_id,
        "owner_id": owner_id,
        "teams": teams,
        "user_slot": user_slot,
        "format": fmt,
        "rounds": rounds,
        "roster_config": config,
        "ranking_set": set_id,
        "ranks": ranks,  # snapshot: {player_id: board rank}
        "ref_ranks": ref_ranks,  # consensus (ECR) snapshot for value analysis
        "extras": extras,  # ranked players missing from the stats dataset
        "order": _build_snake_order(teams, rounds),
        "current_pick_index": 0,
        "picks": [],
        "rosters": {str(t): [] for t in range(1, teams + 1)},
        "available_ids": [p["id"] for p in players] + list(extras.keys()),
        "complete": False,
    }
    _drafts[draft_id] = draft
    _run_ai_until_user_turn(draft, players)
    return _serialize(draft, players)


def get_draft(draft_id: str) -> dict:
    return _drafts.get(draft_id)


def _players_by_id(players: list[dict], draft: Optional[dict] = None) -> dict[str, dict]:
    mapping = {p["id"]: p for p in players}
    if draft:
        mapping.update(draft.get("extras", {}))
    return mapping


def _rank_of(draft: dict, player_id: str) -> int:
    return draft["ranks"].get(player_id, UNRANKED)


def _ref_rank_of(draft: dict, player_id: str) -> int:
    return draft.get("ref_ranks", draft["ranks"]).get(player_id, UNRANKED)


def _current_team(draft: dict) -> Optional[int]:
    if draft["current_pick_index"] >= len(draft["order"]):
        return None
    return draft["order"][draft["current_pick_index"]]


def _current_round(draft: dict) -> int:
    return (draft["current_pick_index"] // draft["teams"]) + 1


def _need_multiplier(team_players: list[dict], position: str, current_round: int, total_rounds: int,
                     config: dict | None = None) -> float:
    counts = roster_rules.position_counts(team_players)
    slots = roster_rules.starter_slots(config)

    if position in ("K", "DEF"):
        if position not in slots:
            return 0.0
        if counts.get(position, 0) >= slots.get(position, 1):
            return 0.0
        if current_round >= total_rounds - 1:
            return 8.0
        return 0.0  # AI never reaches for K/DEF early

    gap = roster_rules.starter_gap(counts, position, config)
    if gap > 0:
        return 1.35
    depth_allowance = 2 if position in roster_rules.FLEX_ELIGIBLE else 1
    if counts.get(position, 0) < slots.get(position, 0) + depth_allowance:
        return 1.0
    return 0.45


def _choose_ai_player(draft: dict, players_by_id: dict[str, dict], team: int) -> dict:
    available = [players_by_id[pid] for pid in draft["available_ids"]]
    team_players = [players_by_id[pid] for pid in draft["rosters"][str(team)]]
    rnd = _current_round(draft)
    pool_size = len(draft["ranks"]) + 50

    scored = []
    for p in available:
        mult = _need_multiplier(team_players, p["position"], rnd, draft["rounds"], draft.get("roster_config"))
        if mult <= 0:
            continue
        board_value = max(pool_size - _rank_of(draft, p["id"]), 1)
        scored.append((board_value * mult, p))

    if not scored:  # e.g. only K/DEF left
        scored = [
            (max(pool_size - _rank_of(draft, p["id"]), 1), p)
            for p in available
        ]

    scored.sort(key=lambda x: -x[0])
    top = scored[:5]
    weights = [s for s, _ in top]
    return random.choices([p for _, p in top], weights=weights, k=1)[0]


def _apply_pick(draft: dict, team: int, chosen: dict) -> None:
    rnd = _current_round(draft)
    pick_no = draft["current_pick_index"] + 1
    draft["picks"].append(
        {
            "pick_no": pick_no,
            "round": rnd,
            "team": team,
            "player_id": chosen["id"],
            "name": chosen["name"],
            "position": chosen["position"],
            "nfl_team": chosen["team"],
            "draft_rank": _rank_of(draft, chosen["id"]),
        }
    )
    draft["rosters"][str(team)].append(chosen["id"])
    draft["available_ids"].remove(chosen["id"])
    draft["current_pick_index"] += 1
    if draft["current_pick_index"] >= len(draft["order"]):
        draft["complete"] = True


def _run_ai_until_user_turn(draft: dict, players: list[dict]) -> None:
    players_by_id = _players_by_id(players, draft)
    while not draft["complete"]:
        team = _current_team(draft)
        if team is None:
            draft["complete"] = True
            break
        if team == draft["user_slot"]:
            break
        chosen = _choose_ai_player(draft, players_by_id, team)
        _apply_pick(draft, team, chosen)


async def make_user_pick(draft_id: str, player_id: str) -> dict:
    draft = _drafts.get(draft_id)
    if not draft:
        raise KeyError("draft not found")
    if draft["complete"]:
        raise ValueError("draft already complete")
    team = _current_team(draft)
    if team != draft["user_slot"]:
        raise ValueError("not the user's turn")
    if player_id not in draft["available_ids"]:
        raise ValueError("player not available")

    players = await dataset.build_dataset()
    players_by_id = _players_by_id(players, draft)
    _apply_pick(draft, team, players_by_id[player_id])
    _run_ai_until_user_turn(draft, players)
    if draft["complete"]:
        await _archive_draft(draft, players)
    return _serialize(draft, players)


async def _archive_draft(draft: dict, players: list[dict]) -> None:
    """Persist a finished draft with its report card so past drafts can be
    reviewed (what graded well, what didn't)."""
    if not draft.get("owner_id"):
        return  # anonymous drafts aren't archived
    try:
        grade = await get_grade(draft["id"])
    except Exception:
        grade = None
    record = {
        "id": draft["id"],
        "owner_id": draft["owner_id"],
        "completed_at": int(time.time()),
        "teams": draft["teams"],
        "user_slot": draft["user_slot"],
        "format": draft["format"],
        "ranking_set": draft["ranking_set"],
        "rounds": draft["rounds"],
        "state": _serialize(draft, players),
        "grade": grade,
    }
    (_history_dir(draft["owner_id"]) / f"{draft['id']}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


def list_history(user_id: str) -> list[dict]:
    out = []
    for path in _history_dir(user_id).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": data["id"],
                    "completed_at": data.get("completed_at"),
                    "teams": data.get("teams"),
                    "user_slot": data.get("user_slot"),
                    "format": data.get("format"),
                    "ranking_set": data.get("ranking_set"),
                    "grade": (data.get("grade") or {}).get("grade"),
                    "league_rank": (data.get("grade") or {}).get("league_rank"),
                }
            )
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    out.sort(key=lambda d: -(d.get("completed_at") or 0))
    return out


def get_history(user_id: str, draft_id: str) -> dict | None:
    path = _history_dir(user_id) / f"{draft_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_history(user_id: str, draft_id: str) -> bool:
    path = _history_dir(user_id) / f"{draft_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


async def serialize_current(draft_id: str) -> dict:
    draft = _drafts.get(draft_id)
    if not draft:
        raise KeyError("draft not found")
    players = await dataset.build_dataset()
    return _serialize(draft, players)


def _with_rank(draft: dict, p: dict) -> dict:
    rank = _rank_of(draft, p["id"])
    return {**p, "draft_rank": (rank if rank < UNRANKED else None)}


def _serialize(draft: dict, players: list[dict]) -> dict:
    players_by_id = _players_by_id(players, draft)
    user_team = int(draft["user_slot"])
    user_players = [players_by_id[pid] for pid in draft["rosters"][str(user_team)]]
    lineup = roster_rules.assign_lineup(user_players, draft["format"], draft.get("roster_config")) if user_players else None

    return {
        "id": draft["id"],
        "teams": draft["teams"],
        "user_slot": draft["user_slot"],
        "format": draft["format"],
        "ranking_set": draft["ranking_set"],
        "roster_config": draft.get("roster_config"),
        "rounds": draft["rounds"],
        "current_pick_index": draft["current_pick_index"],
        "current_round": _current_round(draft) if not draft["complete"] else draft["rounds"],
        "on_the_clock": _current_team(draft),
        "is_user_turn": (not draft["complete"]) and _current_team(draft) == user_team,
        "complete": draft["complete"],
        "picks": draft["picks"],
        "user_roster": [_with_rank(draft, p) for p in user_players],
        "user_lineup": lineup,
        "available_count": len(draft["available_ids"]),
    }


async def get_available(
    draft_id: str,
    position: Optional[str],
    limit: int,
    view_set: Optional[str] = None,
) -> list[dict]:
    """Available players. Ordered by the draft board by default; when
    `view_set` is given (a site's rankings/ADP), each player also carries a
    `view_rank` in that board and the list is ordered by it — lets you
    cross-reference any site's board mid-draft without changing the AI's."""
    draft = _drafts.get(draft_id)
    if not draft:
        raise KeyError("draft not found")

    view_ranks: dict[str, int] = {}
    if view_set:
        try:
            view_ranks = await rankings_store.get_ranks(view_set)
        except Exception:
            view_ranks = {}

    players = await dataset.build_dataset()
    players_by_id = _players_by_id(players, draft)
    available = [players_by_id[pid] for pid in draft["available_ids"]]
    if position:
        wanted = {p.strip().upper() for p in position.split(",")}
        available = [p for p in available if p["position"] in wanted]

    if view_ranks:
        available.sort(key=lambda p: view_ranks.get(p["id"], UNRANKED))
    else:
        available.sort(key=lambda p: _rank_of(draft, p["id"]))

    out = []
    for p in available[:limit]:
        row = _with_rank(draft, p)
        if view_set:
            vr = view_ranks.get(p["id"])
            row["view_rank"] = vr if vr and vr < UNRANKED else None
        out.append(row)
    return out


async def get_suggestions(draft_id: str) -> dict:
    draft = _drafts.get(draft_id)
    if not draft:
        raise KeyError("draft not found")
    if draft["complete"]:
        return {"complete": True, "best_available": [], "best_value": [], "best_fit": []}

    players = await dataset.build_dataset()
    players_by_id = _players_by_id(players, draft)
    available = sorted(
        (players_by_id[pid] for pid in draft["available_ids"]),
        key=lambda p: _rank_of(draft, p["id"]),
    )
    user_players = [players_by_id[pid] for pid in draft["rosters"][str(draft["user_slot"])]]
    counts = roster_rules.position_counts(user_players)
    rnd = _current_round(draft)
    late = rnd >= draft["rounds"] - 1
    pick_no = draft["current_pick_index"] + 1

    def skill(p):
        return p["position"] not in ("K", "DEF")

    # Urgency: once your remaining picks barely cover your open starter
    # slots, every suggestion column narrows to need-filling positions so
    # you can't value-hunt your way into an empty lineup.
    remaining_picks = sum(
        1 for t in draft["order"][draft["current_pick_index"]:] if t == draft["user_slot"]
    )
    config = draft.get("roster_config")
    lineup = roster_rules.assign_lineup(user_players, draft["format"], config)
    open_slots = [slot for slot, p in lineup["starters"].items() if p is None]
    open_positions: set[str] = set()
    for slot in open_slots:
        base = slot.rstrip("0123456789")
        if base == "FLEX":
            open_positions |= roster_rules.FLEX_ELIGIBLE
        elif base == "SUPERFLEX":
            open_positions |= roster_rules.SUPERFLEX_ELIGIBLE
        else:
            open_positions.add(base)
    urgent = bool(open_slots) and remaining_picks <= len(open_slots) + 1

    def allowed(p):
        if urgent and p["position"] not in open_positions:
            return False
        return skill(p) or late or (urgent and p["position"] in open_positions)

    best_available = [
        _with_rank(draft, p) for p in available if allowed(p)
    ][:3]

    # Value = how far a player has fallen past his *consensus* (ECR) rank,
    # weighted relative to that rank so early-board falls dominate (a
    # top-10 player available 8 picks late is a far bigger deal than a
    # rank-240 player available at 250).
    values = []
    for p in available:
        rank = _ref_rank_of(draft, p["id"])
        if rank >= UNRANKED or not allowed(p):
            continue
        fall = pick_no - rank
        if fall > 0:
            values.append((fall / rank, fall, p, rank))
    values.sort(key=lambda x: -x[0])
    best_value = [
        {**_with_rank(draft, p), "value_fall": fall, "value_fall_pct": round(pct * 100), "ref_rank": rank}
        for pct, fall, p, rank in values[:3]
    ]

    # Fit = highest-board-rank player at each position where a starter slot
    # (or flex) is still open.
    fits = []
    seen_positions = set()
    starter_slots_cfg = roster_rules.starter_slots(config)
    has_flex = ("FLEX" in open_positions) or ("SUPERFLEX" in [s.rstrip("0123456789") for s in open_slots])
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        if pos not in starter_slots_cfg and not (pos in open_positions):
            continue
        needed = roster_rules.starter_gap(counts, pos, config) > 0
        if pos in ("K", "DEF") and not late:
            needed = False
        flex_open = has_flex and pos in roster_rules.SUPERFLEX_ELIGIBLE
        if not needed and not flex_open:
            continue
        candidate = next((p for p in available if p["position"] == pos), None)
        if candidate and candidate["id"] not in seen_positions:
            seen_positions.add(candidate["id"])
            reason = f"Fills your open {pos} starter slot" if needed else f"Best {pos} for your open FLEX"
            fits.append({**_with_rank(draft, candidate), "fit_reason": reason})
    fits.sort(key=lambda p: p["draft_rank"] if p["draft_rank"] is not None else UNRANKED)

    # Ideal value at every position: the best available player per position,
    # with how far he's fallen past his board rank and his projected value
    # over replacement — the "who should I be targeting" view each pick.
    by_position = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        # Best *consensus-ranked* available at the position, and how far
        # past his ECR the draft has slipped.
        candidate = min(
            (p for p in available if p["position"] == pos),
            key=lambda p: _ref_rank_of(draft, p["id"]),
            default=None,
        )
        if candidate is None:
            continue
        ref = _ref_rank_of(draft, candidate["id"])
        by_position.append(
            {
                **_with_rank(draft, candidate),
                "ref_rank": ref if ref < UNRANKED else None,
                "value_fall": (pick_no - ref) if ref < UNRANKED else None,
            }
        )

    return {
        "complete": False,
        "pick_no": pick_no,
        "round": rnd,
        "best_available": best_available,
        "best_value": best_value,
        "best_fit": fits[:3],
        "by_position": by_position,
        "remaining_picks": remaining_picks,
        "open_starter_slots": open_slots,
        "urgent": urgent,
    }


# ---------------------------------------------------------------- grading

_PERCENTILE_GRADES = [
    (0.0, "A+"), (0.25, "A"), (0.45, "B+"), (0.65, "B"), (0.85, "C+"), (1.01, "C"),
]


def _grade_from_position(position: int, teams: int) -> str:
    if position == 1:
        return "A+"
    frac = (position - 1) / teams
    for threshold, grade in _PERCENTILE_GRADES:
        if frac <= threshold:
            return grade
    return "C"


async def get_grade(draft_id: str) -> dict:
    draft = _drafts.get(draft_id)
    if not draft:
        raise KeyError("draft not found")
    if not draft["complete"]:
        raise ValueError("draft is not complete yet")

    fmt = draft["format"]
    cfg = draft.get("roster_config")
    players = await dataset.build_dataset()
    players_by_id = _players_by_id(players, draft)

    # League table: every team's starting-lineup value.
    league = []
    for t in range(1, draft["teams"] + 1):
        roster = [players_by_id[pid] for pid in draft["rosters"][str(t)]]
        graded = roster_analyzer.grade_players(roster, fmt, cfg)
        league.append(
            {
                "team": t,
                "is_user": t == draft["user_slot"],
                "starter_vbd": graded["starter_vbd"],
                "effective_vbd": graded["effective_vbd"],
                "missing_starter_slots": graded["missing_starter_slots"],
            }
        )
    league.sort(key=lambda x: -x["effective_vbd"])
    for i, row in enumerate(league, start=1):
        row["rank"] = i

    user_row = next(r for r in league if r["is_user"])
    overall_grade = _grade_from_position(user_row["rank"], draft["teams"])

    # Positional strengths/weaknesses vs league average (starters only).
    user_roster = [players_by_id[pid] for pid in draft["rosters"][str(draft["user_slot"])]]
    positional = []
    for pos in ("QB", "RB", "WR", "TE"):
        league_vbds = []
        user_vbd = 0.0
        for t in range(1, draft["teams"] + 1):
            roster = [players_by_id[pid] for pid in draft["rosters"][str(t)]]
            lineup = roster_rules.assign_lineup(roster, fmt, cfg)
            vbd = sum(
                roster_rules.player_vbd(p, fmt)
                for p in lineup["starters"].values()
                if p is not None and p["position"] == pos
            )
            league_vbds.append(vbd)
            if t == draft["user_slot"]:
                user_vbd = vbd
        avg = sum(league_vbds) / len(league_vbds) if league_vbds else 0.0
        diff = round(user_vbd - avg, 1)
        verdict = "strength" if diff >= 25 else "weakness" if diff <= -25 else "average"
        positional.append(
            {"position": pos, "your_vbd": round(user_vbd, 1), "league_avg_vbd": round(avg, 1), "diff": diff, "verdict": verdict}
        )

    # Slips: for each user pick, was a clearly better *consensus-ranked*
    # (ECR) player available who also fit the roster at that moment?
    ref_ranks = draft.get("ref_ranks", draft["ranks"])
    slips = []
    taken: set[str] = set()
    user_so_far: list[dict] = []
    for pick in draft["picks"]:
        if pick["team"] != draft["user_slot"]:
            taken.add(pick["player_id"])
            continue

        picked_rank = ref_ranks.get(pick["player_id"], UNRANKED)
        counts = roster_rules.position_counts(user_so_far)
        late = pick["round"] >= draft["rounds"] - 1

        best_alt = None
        for pid, rank in sorted(ref_ranks.items(), key=lambda kv: kv[1]):
            if pid in taken or pid == pick["player_id"]:
                continue
            alt = players_by_id.get(pid)
            if alt is None:
                continue
            if alt["position"] in ("K", "DEF") and not late:
                continue
            mult = _need_multiplier(user_so_far, alt["position"], pick["round"], draft["rounds"], cfg)
            if mult < 1.0:  # wouldn't have improved the roster construction
                continue
            best_alt = (alt, rank)
            break

        # A pick outside the consensus list entirely counts as a slip when a
        # clearly better consensus player was on the board; cap the rank
        # math so the report stays readable.
        picked_display = picked_rank if picked_rank < UNRANKED else None
        effective_picked = min(picked_rank, len(ref_ranks) + 50)
        if best_alt and effective_picked - best_alt[1] >= SLIP_RANK_THRESHOLD:
            alt, alt_rank = best_alt
            vbd_diff = round(
                roster_rules.player_vbd(alt, fmt)
                - roster_rules.player_vbd(players_by_id[pick["player_id"]], fmt),
                1,
            )
            slips.append(
                {
                    "round": pick["round"],
                    "pick_no": pick["pick_no"],
                    "picked": pick["name"],
                    "picked_position": pick["position"],
                    "picked_rank": picked_display,
                    "better_option": alt["name"],
                    "better_position": alt["position"],
                    "better_rank": alt_rank,
                    "rank_diff": effective_picked - alt_rank,
                    "vbd_diff": vbd_diff,
                }
            )

        taken.add(pick["player_id"])
        user_so_far.append(players_by_id[pick["player_id"]])

    slips.sort(key=lambda s: -s["rank_diff"])
    potential_gain = round(sum(max(s["vbd_diff"], 0) for s in slips[:5]), 1)

    strengths = [p for p in positional if p["verdict"] == "strength"]
    weaknesses = [p for p in positional if p["verdict"] == "weakness"]
    summary_bits = [f"You finished #{user_row['rank']} of {draft['teams']} teams in projected starting-lineup value."]
    if user_row["missing_starter_slots"]:
        summary_bits.append(
            "You never filled " + ", ".join(user_row["missing_starter_slots"])
            + " — an empty starter slot scores zero every week, which sinks the grade regardless of your other picks."
        )
    if strengths:
        summary_bits.append("Strengths: " + ", ".join(p["position"] for p in strengths) + ".")
    if weaknesses:
        summary_bits.append("Weaknesses: " + ", ".join(p["position"] for p in weaknesses) + ".")
    if slips:
        summary_bits.append(
            f"{len(slips)} pick(s) slipped past better board options — cleaner picks could have added ~{potential_gain} VBD."
        )
    else:
        summary_bits.append("No significant reaches — you consistently took the best available fit.")

    return {
        "grade": overall_grade,
        "format": fmt,
        "ranking_set": draft["ranking_set"],
        "league_rank": user_row["rank"],
        "teams": draft["teams"],
        "summary": " ".join(summary_bits),
        "league_table": league,
        "positional": positional,
        "slips": slips[:8],
        "potential_vbd_gain": potential_gain,
    }
