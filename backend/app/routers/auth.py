from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest
from app.schemas.common import Resp
from app.services.auth_service import (
    register_user, login_user, create_access_token, create_refresh_token,
    change_password, update_profile,
)
from app.dependencies import get_current_user, get_refresh_token_user
from app.models.db_models import User

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])

@router.post("/register", status_code=201)
async def register(body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        user = await register_user(db, body.username, body.email, body.password)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(status_code=409, detail={"code": int(code), "msg": msg})
    access = create_access_token(user.user_id)
    refresh = create_refresh_token(user.user_id)
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="strict", path="/api/v2/auth/refresh", max_age=7*24*3600)
    return Resp.ok({"access_token": access, "token_type": "Bearer", "expires_in": 86400,
                    "user": {"user_id": user.user_id, "username": user.username, "email": user.email}})

@router.post("/login")
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        user = await login_user(db, body.email, body.password)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        status = 429 if code == "4291" else 401
        raise HTTPException(status_code=status, detail={"code": int(code), "msg": msg})
    access = create_access_token(user.user_id)
    refresh = create_refresh_token(user.user_id)
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="strict", path="/api/v2/auth/refresh", max_age=7*24*3600)
    return Resp.ok({"access_token": access, "token_type": "Bearer", "expires_in": 86400,
                    "user": {"user_id": user.user_id, "username": user.username, "email": user.email}})

@router.post("/refresh")
async def refresh_token(response: Response, user: User = Depends(get_refresh_token_user)):
    access = create_access_token(user.user_id)
    new_refresh = create_refresh_token(user.user_id)
    response.set_cookie("refresh_token", new_refresh, httponly=True, samesite="strict", path="/api/v2/auth/refresh", max_age=7*24*3600)
    return Resp.ok({"access_token": access, "token_type": "Bearer", "expires_in": 86400})

@router.post("/logout")
async def logout(response: Response, user: User = Depends(get_current_user)):
    response.delete_cookie("refresh_token")
    return Resp.ok(msg="已退出登录")

@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return Resp.ok({"user_id": user.user_id, "username": user.username, "email": user.email,
                    "created_at": user.created_at.isoformat() + "Z"})

@router.patch("/me")
async def update_me(body: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        updated = await update_profile(db, user.user_id, username=body.get("username"), email=body.get("email"))
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(status_code=409 if code == "4092" else 400, detail={"code": int(code), "msg": msg})
    return Resp.ok({"user_id": updated.user_id, "username": updated.username, "email": updated.email})

@router.post("/change-password")
async def change_password_route(body: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    current = body.get("current_password") or ""
    new = body.get("new_password") or ""
    if len(new) < 8:
        raise HTTPException(400, {"code": 4001, "msg": "新密码至少8位"})
    try:
        await change_password(db, user.user_id, current, new)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(status_code=401 if code == "4011" else 400, detail={"code": int(code), "msg": msg})
    return Resp.ok(msg="密码已更新")
