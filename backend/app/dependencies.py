from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.database import get_db
from app.models.db_models import User

bearer = HTTPBearer(auto_error=False)

def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail={"code": 4013, "msg": "Token已过期，请刷新"})

async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not cred:
        raise HTTPException(status_code=401, detail={"code": 4010, "msg": "未提供认证信息"})
    payload = _decode(cred.credentials)
    user_id: str = payload.get("sub", "")
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail={"code": 4010, "msg": "用户不存在"})
    return user

async def get_refresh_token_user(
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not refresh_token:
        raise HTTPException(status_code=401, detail={"code": 4012, "msg": "登录已过期，请重新登录"})
    payload = _decode(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail={"code": 4012, "msg": "无效的 Refresh Token"})
    user_id: str = payload.get("sub", "")
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail={"code": 4012, "msg": "用户不存在"})
    return user
