from __future__ import annotations

from fastapi import APIRouter

from app.services import dataset

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
async def get_meta():
    players = await dataset.build_dataset()
    return {
        "season": dataset.season_in_use(),
        "projection_season": dataset.projection_season_in_use(),
        "player_count": len(players),
    }
