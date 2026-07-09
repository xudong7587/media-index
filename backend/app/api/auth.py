from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.config import get_settings
from app.core.security import check_password, create_session, require_user
from app.schemas.common import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    if not check_password(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    settings = get_settings()
    token = create_session(payload.username)
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return {"ok": True, "user": payload.username}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(get_settings().cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = require_user(request)
    return {"ok": True, "user": user.username}

