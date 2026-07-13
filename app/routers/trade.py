from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import current_user
from app.services import league_store, trade_analyzer, trade_matcher

router = APIRouter(prefix="/api/trade", tags=["trade"])


class TradeRequest(BaseModel):
    team_a_sends: list[str]
    team_b_sends: list[str]
    format: str = "ppr"
    team_a_roster: list[str] | None = None
    team_b_roster: list[str] | None = None


@router.post("/analyze")
async def analyze_trade(req: TradeRequest):
    if req.format not in ("standard", "half_ppr", "ppr"):
        raise HTTPException(400, "invalid format")
    if not req.team_a_sends or not req.team_b_sends:
        raise HTTPException(400, "both sides must send at least one player")
    return await trade_analyzer.analyze_trade(
        req.team_a_sends,
        req.team_b_sends,
        req.format,
        req.team_a_roster,
        req.team_b_roster,
    )


@router.get("/matches")
async def trade_matches(
    league_key: str = Query(...),
    team_id: str = Query(...),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    user: dict = Depends(current_user),
):
    league = league_store.get_league(user["id"], league_key)
    if league is None:
        raise HTTPException(404, "league not found")
    try:
        return await trade_matcher.find_matches(league, team_id, format)
    except ValueError as e:
        raise HTTPException(400, str(e))
