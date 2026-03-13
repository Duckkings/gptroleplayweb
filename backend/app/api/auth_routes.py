from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.core.auth import SESSION_COOKIE, load_session, register_user, reset_user_password, sign_session, validate_username, verify_user


logger = logging.getLogger("roleplay.api.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register")
async def auth_register(payload: dict) -> dict:
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    try:
        register_user(username, password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("auth register failed for %r", username)
        raise HTTPException(status_code=500, detail="auth register failed") from exc
    return {"ok": True}


@router.post("/login")
async def auth_login(payload: dict, response: Response) -> dict:
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    try:
        username = validate_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        verified = verify_user(username, password)
    except Exception as exc:
        logger.exception("auth login failed during verification for %r", username)
        raise HTTPException(status_code=500, detail="auth login failed") from exc

    if not verified:
        raise HTTPException(status_code=401, detail="invalid username or password")

    token = sign_session(username)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 30,
    )
    return {"ok": True, "username": username}


@router.post("/logout")
async def auth_logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.post("/reset-password")
async def auth_reset_password(payload: dict) -> dict:
    username = str(payload.get("username") or "")
    current_password = str(payload.get("current_password") or "")
    new_password = str(payload.get("new_password") or "")
    try:
        reset_user_password(username, current_password, new_password)
    except ValueError as exc:
        detail = str(exc)
        status_code = 401 if detail == "invalid username or current password" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        logger.exception("auth reset password failed for %r", username)
        raise HTTPException(status_code=500, detail="auth reset password failed") from exc
    return {"ok": True}


@router.get("/me")
async def auth_me(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    sess = load_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="not logged in")
    return {"ok": True, "username": sess.username}
