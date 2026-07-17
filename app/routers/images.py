"""Proxies player headshots / team logos from Sleeper's CDN with disk
caching, so the frontend only makes same-origin image requests."""
from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.paths import CACHE_DIR

router = APIRouter(prefix="/api/img", tags=["images"])

IMG_DIR = CACHE_DIR / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)

_SAFE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
_HEADERS = {"Cache-Control": "public, max-age=86400"}


async def _proxy(cache_name: str, url: str, media_type: str) -> Response:
    path = IMG_DIR / cache_name
    miss_marker = IMG_DIR / (cache_name + ".miss")
    if path.exists():
        return FileResponse(path, media_type=media_type, headers=_HEADERS)
    if miss_marker.exists():
        return Response(status_code=404)

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError:
        return Response(status_code=404)

    if resp.status_code != 200 or not resp.content:
        miss_marker.touch()
        return Response(status_code=404)

    path.write_bytes(resp.content)
    return FileResponse(path, media_type=media_type, headers=_HEADERS)


@router.get("/player/{player_id}")
async def player_image(player_id: str):
    if not _SAFE.match(player_id):
        return Response(status_code=404)
    return await _proxy(
        f"p_{player_id}.jpg",
        f"https://sleepercdn.com/content/nfl/players/thumb/{player_id}.jpg",
        "image/jpeg",
    )


@router.get("/team/{abbr}")
async def team_image(abbr: str):
    if not _SAFE.match(abbr):
        return Response(status_code=404)
    return await _proxy(
        f"t_{abbr.lower()}.png",
        f"https://sleepercdn.com/images/team_logos/nfl/{abbr.lower()}.png",
        "image/png",
    )
