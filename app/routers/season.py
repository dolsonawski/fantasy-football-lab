from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import current_user
from app.services import league_store, season

router = APIRouter(prefix="/api/season", tags=["season"])


def _league(user: dict, league_key: str) -> dict:
    league = league_store.get_league(user["id"], league_key)
    if league is None:
        raise HTTPException(404, "league not found — import it on the Import tab first")
    return league


@router.get("/start-sit")
async def start_sit(
    league_key: str = Query(...),
    team_id: str = Query(...),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    week: int | None = Query(default=None, ge=1, le=18),
    user: dict = Depends(current_user),
):
    league = _league(user, league_key)
    try:
        return await season.start_sit(league, team_id, format, week=week)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/bye-planner")
async def bye_planner(
    league_key: str = Query(...),
    team_id: str = Query(...),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    user: dict = Depends(current_user),
):
    league = _league(user, league_key)
    try:
        return await season.bye_planner(league, team_id, format)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/waivers")
async def waivers(
    league_key: str = Query(...),
    team_id: str = Query(...),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    user: dict = Depends(current_user),
):
    league = _league(user, league_key)
    try:
        return await season.waiver_targets(league, team_id, format)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/playoff-outlook")
async def playoff_outlook(
    league_key: str = Query(...),
    team_id: str = Query(...),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    user: dict = Depends(current_user),
):
    league = _league(user, league_key)
    try:
        return await season.playoff_outlook(league, team_id, format)
    except ValueError as e:
        raise HTTPException(400, str(e))
