from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import roster_analyzer

router = APIRouter(prefix="/api/roster", tags=["roster"])


class AnalyzeRequest(BaseModel):
    player_ids: list[str]
    format: str = "ppr"


@router.post("/analyze")
async def analyze_roster(req: AnalyzeRequest):
    if req.format not in ("standard", "half_ppr", "ppr"):
        raise HTTPException(400, "invalid format")
    return await roster_analyzer.analyze_player_ids(req.player_ids, req.format)


@router.get("/sleeper")
async def analyze_sleeper_roster(
    league_id: str = Query(...),
    roster_id: int = Query(...),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
):
    try:
        return await roster_analyzer.analyze_sleeper_roster(league_id, roster_id, format)
    except ValueError as e:
        raise HTTPException(404, str(e))
