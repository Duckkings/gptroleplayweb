from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, Request

from app.core.auth import SESSION_COOKIE, register_user, verify_user, sign_session, load_session, validate_username

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register")
async def auth_register(payload: dict) -> dict:
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    try:
        register_user(username, password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/login")
async def auth_login(payload: dict, response: Response) -> dict:
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    try:
        username = validate_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not verify_user(username, password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = sign_session(username)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # set true when behind https
        max_age=60 * 60 * 24 * 30,
    )
    return {"ok": True, "username": username}


@router.post("/logout")
async def auth_logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
async def auth_me(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    sess = load_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录")
    return {"ok": True, "username": sess.username}
