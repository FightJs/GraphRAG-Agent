from datetime import datetime, timedelta
import bcrypt
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import User
import uuid

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_access_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "access"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "refresh"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

async def register_user(db: AsyncSession, username: str, email: str, password: str) -> User:
    result = await db.execute(select(User).where((User.email == email) | (User.username == username)))
    existing = result.scalar_one_or_none()
    if existing:
        if existing.email == email.lower():
            raise ValueError("4092:该邮箱已被注册")
        raise ValueError("4092:该用户名已被使用")
    user = User(
        user_id=str(uuid.uuid4()),
        username=username,
        email=email.lower(),
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def login_user(db: AsyncSession, email: str, password: str) -> User:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("4011:邮箱或密码错误")
    if user.locked_until and user.locked_until > datetime.utcnow():
        raise ValueError("4291:账户已锁定，请15分钟后再试")
    if not verify_password(password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=15)
        await db.commit()
        raise ValueError("4011:邮箱或密码错误")
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)
    return user

async def change_password(db: AsyncSession, user_id: str, current_password: str, new_password: str) -> User:
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("4011:用户不存在")
    if not verify_password(current_password, user.password_hash):
        raise ValueError("4011:当前密码错误")
    user.password_hash = hash_password(new_password)
    await db.commit()
    await db.refresh(user)
    return user

async def update_profile(db: AsyncSession, user_id: str, username: str | None = None, email: str | None = None) -> User:
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("4011:用户不存在")
    if username is not None:
        dup = await db.execute(select(User).where(User.username == username, User.user_id != user_id))
        if dup.scalar_one_or_none():
            raise ValueError("4092:该用户名已被使用")
        user.username = username
    if email is not None:
        dup = await db.execute(select(User).where(User.email == email.lower(), User.user_id != user_id))
        if dup.scalar_one_or_none():
            raise ValueError("4092:该邮箱已被注册")
        user.email = email.lower()
    await db.commit()
    await db.refresh(user)
    return user
