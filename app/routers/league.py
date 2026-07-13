from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import current_user
from app.services import league_store

router = APIRouter(prefix="/api/league", tags=["league"])


class ImportLeagueRequest(BaseModel):
    platform: str  # "espn" | "sleeper"
    league_id: str
    espn_s2: str | None = None
    swid: str | None = None


@router.post("/import")
async def import_league(req: ImportLeagueRequest, user: dict = Depends(current_user)):
    try:
        if req.platform == "sleeper":
            return await league_store.import_sleeper_league(user["id"], req.league_id.strip())
        if req.platform == "espn":
            return await league_store.import_espn_league(
                user["id"],
                req.league_id.strip(),
                (req.espn_s2 or "").strip() or None,
                (req.swid or "").strip() or None,
            )
        raise HTTPException(400, "platform must be 'espn' or 'sleeper'")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError:
        raise HTTPException(502, "League platform could not be reached")


@router.get("")
async def list_leagues(user: dict = Depends(current_user)):
    return {"leagues": league_store.list_leagues(user["id"])}


@router.get("/{key}")
async def get_league(key: str, user: dict = Depends(current_user)):
    league = league_store.get_league(user["id"], key)
    if league is None:
        raise HTTPException(404, "league not found")
    return league


@router.delete("/{key}")
async def delete_league(key: str, user: dict = Depends(current_user)):
    if not league_store.delete_league(user["id"], key):
        raise HTTPException(404, "league not found")
    return {"deleted": key}
