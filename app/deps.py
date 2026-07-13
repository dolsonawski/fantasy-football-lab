"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.services import auth


def current_user(request: Request) -> dict:
    """Resolves the signed-in user from the session cookie, or 401s."""
    token = request.cookies.get(auth.COOKIE_NAME)
    user = auth.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user
