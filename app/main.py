from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

from app.routers import players, rankings, draft, roster, trade, meta, images, league, season

app = FastAPI(title="Fantasy Football App")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Force the browser to revalidate JS/CSS/HTML every load (via ETag), so
    a code update is never masked by a stale cached module."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.include_router(players.router)
app.include_router(rankings.router)
app.include_router(draft.router)
app.include_router(roster.router)
app.include_router(trade.router)
app.include_router(meta.router)
app.include_router(images.router)
app.include_router(league.router)
app.include_router(season.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
