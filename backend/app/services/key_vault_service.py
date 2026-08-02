from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet
import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db_models import UserApiKey

SUPPORTED_PROVIDERS = ("deepseek", "mineru", "embedding")


@dataclass(frozen=True)
class StoredKeyStatus:
    key_id: str
    provider: str
    key_hint: str
    is_verified: bool
    verified_at: datetime


def _fernet() -> Fernet:
    encryption_key = settings.API_KEY_ENCRYPTION_KEY
    if not encryption_key:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY must be configured")
    try:
        return Fernet(encryption_key.encode())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY must be configured with a valid Fernet key") from exc


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def _key_hint(secret: str) -> str:
    if len(secret) <= 4:
        return "****"
    return secret[-4:]


async def store_verified_key(
    db: AsyncSession, user_id: str, provider: str, secret: str
) -> StoredKeyStatus:
    encrypted_secret = encrypt_secret(secret)
    values = {
        "encrypted_secret": encrypted_secret,
        "key_hint": _key_hint(secret),
        "is_verified": True,
        "verified_at": datetime.utcnow(),
    }
    update_result = await db.execute(
        update(UserApiKey)
        .where(UserApiKey.user_id == user_id, UserApiKey.provider == provider)
        .values(**values)
    )

    if update_result.rowcount == 0:
        row = UserApiKey(
            user_id=user_id,
            provider=provider,
            **values,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            await db.execute(
                update(UserApiKey)
                .where(UserApiKey.user_id == user_id, UserApiKey.provider == provider)
                .values(**values)
            )

    await db.commit()
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider,
        )
    )
    row = result.scalar_one()
    return StoredKeyStatus(
        key_id=row.key_id,
        provider=row.provider,
        key_hint=row.key_hint,
        is_verified=row.is_verified,
        verified_at=row.verified_at,
    )


def status_to_dict(status: StoredKeyStatus) -> dict:
    return {
        "provider": status.provider,
        "configured": True,
        "is_verified": status.is_verified,
        "key_hint": status.key_hint,
        "verified_at": status.verified_at,
    }


async def get_statuses(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(select(UserApiKey).where(UserApiKey.user_id == user_id))
    rows = {row.provider: row for row in result.scalars()}
    providers = []
    for provider in SUPPORTED_PROVIDERS:
        row = rows.get(provider)
        providers.append(
            {
                "provider": provider,
                "configured": row is not None,
                "is_verified": bool(row and row.is_verified),
                "key_hint": row.key_hint if row else None,
                "verified_at": row.verified_at if row else None,
            }
        )
    return {"providers": providers, "ready": all(p["is_verified"] for p in providers)}


async def missing_providers(db: AsyncSession, user_id: str) -> list[str]:
    statuses = await get_statuses(db, user_id)
    return [item["provider"] for item in statuses["providers"] if not item["is_verified"]]


async def delete_key(db: AsyncSession, user_id: str, provider: str) -> None:
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == user_id, UserApiKey.provider == provider)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


async def get_verified_secret(db: AsyncSession, user_id: str, provider: str) -> str:
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider,
            UserApiKey.is_verified.is_(True),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"缺少已验证的 {provider} API Key")
    return decrypt_secret(row.encrypted_secret)


async def verify_provider(provider: str, api_key: str) -> None:
    try:
        if provider == "deepseek":
            await _verify_deepseek(api_key)
        elif provider == "mineru":
            await _verify_mineru(api_key)
        elif provider == "embedding":
            await _verify_openrouter_embedding(api_key)
        else:
            raise ValueError("不支持的 API Key 类型")
    except httpx.HTTPError as exc:
        raise ValueError("验证失败：凭据无效或服务暂不可用") from exc


async def _verify_deepseek(api_key: str) -> None:
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"}, json=payload,
        )
    response.raise_for_status()


async def _verify_mineru(api_key: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{settings.MINERU_BASE_URL}/extract/task/00000000-0000-4000-8000-000000000000",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if response.status_code == 401:
        raise ValueError("验证失败：MinerU API Key 无效或已过期")
    if response.status_code == 403:
        raise ValueError("验证失败：MinerU API Key 没有访问权限")
    if response.status_code >= 500:
        raise ValueError("验证失败：MinerU 服务暂不可用")


async def _verify_openrouter_embedding(api_key: str) -> None:
    payload = {"model": settings.OPENROUTER_EMBEDDING_MODEL, "input": "GraphRAG health check"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"}, json=payload,
        )
    response.raise_for_status()
    if not response.json().get("data"):
        raise ValueError("验证失败：Embedding 服务未返回向量")
