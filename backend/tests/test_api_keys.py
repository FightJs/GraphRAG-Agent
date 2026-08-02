import uuid

import pytest
from sqlalchemy import select

from app.models.db_models import User, UserApiKey
from app.services import key_vault_service
from app.database import AsyncSessionLocal


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def test_user(db_session):
    suffix = uuid.uuid4().hex
    user = User(
        username=f"vault-{suffix}",
        email=f"vault-{suffix}@example.test",
        password_hash="not-used",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_store_key_encrypts_secret_and_returns_safe_status(db_session, test_user):
    secret = "test-secret-1234"

    status = await key_vault_service.store_verified_key(
        db_session, test_user.user_id, "deepseek", secret
    )

    row = await db_session.get(UserApiKey, status.key_id)
    assert row.encrypted_secret != secret
    assert status.key_hint == "1234"
    assert status.is_verified is True


async def test_store_key_upserts_the_same_owner_provider(db_session, test_user):
    first = await key_vault_service.store_verified_key(
        db_session, test_user.user_id, "deepseek", "test-secret-1234"
    )
    second = await key_vault_service.store_verified_key(
        db_session, test_user.user_id, "deepseek", "replacement-5678"
    )

    result = await db_session.execute(
        select(UserApiKey).where(UserApiKey.user_id == test_user.user_id)
    )
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].key_id == first.key_id == second.key_id
    assert rows[0].key_hint == "5678"
    assert key_vault_service.decrypt_secret(rows[0].encrypted_secret) == "replacement-5678"


async def test_store_key_masks_short_secret_hints(db_session, test_user):
    secret = "abc"

    status = await key_vault_service.store_verified_key(
        db_session, test_user.user_id, "mineru", secret
    )

    assert status.key_hint == "****"
    assert status.key_hint != secret


@pytest.mark.parametrize("encryption_key", ["", "not-a-valid-fernet-key"])
def test_encrypt_requires_valid_deployment_key_without_exposing_secret(monkeypatch, encryption_key):
    secret = "test-secret-not-for-errors"
    monkeypatch.setattr(key_vault_service.settings, "API_KEY_ENCRYPTION_KEY", encryption_key)

    with pytest.raises(RuntimeError, match="API_KEY_ENCRYPTION_KEY") as error:
        key_vault_service.encrypt_secret(secret)

    assert secret not in str(error.value)
