from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.deps import current_user  # noqa: F401  (used by /me)
from app.paths import secure_cookies
from app.services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = auth.create_session(user_id)
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        max_age=auth.SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(),
        path="/",
    )


@router.post("/signup")
async def signup(req: SignupRequest, response: Response):
    try:
        user = auth.create_user(req.username, req.password, req.display_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _set_session_cookie(response, user["id"])
    return user


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    user = auth.verify_login(req.username, req.password)
    if user is None:
        raise HTTPException(401, "Incorrect username or password.")
    _set_session_cookie(response, user["id"])
    return user


@router.post("/logout")
async def logout(request: Request, response: Response):
    auth.delete_session(request.cookies.get(auth.COOKIE_NAME))
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user
