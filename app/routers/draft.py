from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import current_user
from app.services import draft_engine, live_draft

router = APIRouter(prefix="/api/draft", tags=["draft"])


class StartDraftRequest(BaseModel):
    teams: int = 12
    user_slot: int = 1
    format: str = "ppr"
    rounds: int | None = None
    ranking_set: str | None = None
    roster_config: dict | None = None


class PickRequest(BaseModel):
    player_id: str


def _owned_draft(draft_id: str, user: dict) -> dict:
    draft = draft_engine.get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    if draft.get("owner_id") and draft["owner_id"] != user["id"]:
        raise HTTPException(403, "that draft belongs to another account")
    return draft


@router.post("/start")
async def start_draft(req: StartDraftRequest, user: dict = Depends(current_user)):
    if req.format not in ("standard", "half_ppr", "ppr"):
        raise HTTPException(400, "invalid format")
    try:
        return await draft_engine.create_draft(
            req.teams, req.user_slot, req.format, req.rounds, req.ranking_set,
            owner_id=user["id"], roster_config=req.roster_config,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/live/{sleeper_draft_id}")
async def live_draft_snapshot(
    sleeper_draft_id: str,
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    user: dict = Depends(current_user),
):
    try:
        return await live_draft.snapshot(sleeper_draft_id.strip(), format)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/history")
async def draft_history(user: dict = Depends(current_user)):
    return {"drafts": draft_engine.list_history(user["id"])}


@router.get("/history/{draft_id}")
async def draft_history_detail(draft_id: str, user: dict = Depends(current_user)):
    record = draft_engine.get_history(user["id"], draft_id)
    if record is None:
        raise HTTPException(404, "draft not found in history")
    return record


@router.delete("/history/{draft_id}")
async def delete_draft_history(draft_id: str, user: dict = Depends(current_user)):
    if not draft_engine.delete_history(user["id"], draft_id):
        raise HTTPException(404, "draft not found in history")
    return {"deleted": draft_id}


@router.get("/{draft_id}")
async def get_draft(draft_id: str, user: dict = Depends(current_user)):
    _owned_draft(draft_id, user)
    return await draft_engine.serialize_current(draft_id)


@router.get("/{draft_id}/available")
async def available_players(
    draft_id: str,
    position: str | None = Query(default=None),
    view_set: str | None = Query(default=None),
    limit: int = Query(default=50, le=300),
    user: dict = Depends(current_user),
):
    _owned_draft(draft_id, user)
    return await draft_engine.get_available(draft_id, position, limit, view_set)


@router.get("/{draft_id}/suggestions")
async def draft_suggestions(draft_id: str, user: dict = Depends(current_user)):
    _owned_draft(draft_id, user)
    return await draft_engine.get_suggestions(draft_id)


@router.get("/{draft_id}/grade")
async def draft_grade(draft_id: str, user: dict = Depends(current_user)):
    _owned_draft(draft_id, user)
    try:
        return await draft_engine.get_grade(draft_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{draft_id}/pick")
async def make_pick(draft_id: str, req: PickRequest, user: dict = Depends(current_user)):
    _owned_draft(draft_id, user)
    try:
        return await draft_engine.make_user_pick(draft_id, req.player_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
