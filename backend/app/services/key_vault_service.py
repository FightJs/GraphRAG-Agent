from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db_models import UserApiKey


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
