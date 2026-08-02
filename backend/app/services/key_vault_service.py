from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import select
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
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider,
        )
    )
    row = result.scalar_one_or_none()
    encrypted_secret = encrypt_secret(secret)

    if row is None:
        row = UserApiKey(
            user_id=user_id,
            provider=provider,
            encrypted_secret=encrypted_secret,
            key_hint=_key_hint(secret),
            is_verified=True,
        )
        db.add(row)
    else:
        row.encrypted_secret = encrypted_secret
        row.key_hint = _key_hint(secret)
        row.is_verified = True
        row.verified_at = datetime.utcnow()

    await db.commit()
    await db.refresh(row)
    return StoredKeyStatus(
        key_id=row.key_id,
        provider=row.provider,
        key_hint=row.key_hint,
        is_verified=row.is_verified,
        verified_at=row.verified_at,
    )
