import asyncio
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


async def test_concurrent_first_time_saves_keep_one_provider_row(test_user):
    async def save(secret: str):
        async with AsyncSessionLocal() as session:
            return await key_vault_service.store_verified_key(
                session, test_user.user_id, "embedding", secret
            )

    first, second = await asyncio.gather(
        save("concurrent-first-1234"),
        save("concurrent-second-5678"),
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == test_user.user_id,
                UserApiKey.provider == "embedding",
            )
        )
        rows = list(result.scalars())

    assert len(rows) == 1
    assert first.key_id == second.key_id == rows[0].key_id
    assert key_vault_service.decrypt_secret(rows[0].encrypted_secret) in {
        "concurrent-first-1234",
        "concurrent-second-5678",
    }


async def test_store_key_masks_short_secret_hints(db_session, test_user):
    secret = "abc"

    status = await key_vault_service.store_verified_key(
        db_session, test_user.user_id, "mineru", secret
    )

    assert status.key_hint == "****"
    assert status.key_hint != secret


async def test_business_api_requires_all_verified_providers(client):
    suffix = uuid.uuid4().hex
    payload = {
        "username": f"gate{suffix[:16]}",
        "email": f"gate-{suffix}@example.test",
        "password": "TestPass123",
    }
    response = await client.post("/api/v2/auth/register", json=payload)
    token = response.json()["data"]["access_token"]
    response = await client.get("/api/v2/kbs", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 428
    assert set(response.json()["detail"]["missing_providers"]) == {"deepseek", "mineru", "embedding"}


async def test_settings_api_saves_verified_key_and_never_returns_plaintext(client, monkeypatch):
    suffix = uuid.uuid4().hex
    registration = await client.post(
        "/api/v2/auth/register",
        json={"username": f"keys{suffix[:16]}", "email": f"keys-{suffix}@example.test", "password": "TestPass123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['data']['access_token']}"}

    async def accept(provider: str, api_key: str) -> None:
        return None

    monkeypatch.setattr(key_vault_service, "verify_provider", accept)
    secret = "secret-9876"
    response = await client.put(
        "/api/v2/settings/api-keys/deepseek", json={"api_key": secret}, headers=headers
    )
    assert response.status_code == 200
    assert secret not in response.text

    response = await client.get("/api/v2/settings/api-keys", headers=headers)
    assert response.status_code == 200
    assert secret not in response.text
    deepseek = next(item for item in response.json()["data"]["providers"] if item["provider"] == "deepseek")
    assert deepseek["key_hint"] == "9876"


async def test_settings_api_does_not_persist_a_rejected_key(client, monkeypatch):
    suffix = uuid.uuid4().hex
    registration = await client.post(
        "/api/v2/auth/register",
        json={"username": f"reject{suffix[:14]}", "email": f"reject-{suffix}@example.test", "password": "TestPass123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['data']['access_token']}"}

    async def reject(provider: str, api_key: str) -> None:
        raise ValueError("验证失败：凭据无效")

    monkeypatch.setattr(key_vault_service, "verify_provider", reject)
    response = await client.put(
        "/api/v2/settings/api-keys/mineru", json={"api_key": "invalid-credential"}, headers=headers
    )
    assert response.status_code == 422
    response = await client.get("/api/v2/settings/api-keys", headers=headers)
    mineru = next(item for item in response.json()["data"]["providers"] if item["provider"] == "mineru")
    assert mineru["configured"] is False


@pytest.mark.parametrize("encryption_key", ["", "not-a-valid-fernet-key"])
def test_encrypt_requires_valid_deployment_key_without_exposing_secret(monkeypatch, encryption_key):
    secret = "test-secret-not-for-errors"
    monkeypatch.setattr(key_vault_service.settings, "API_KEY_ENCRYPTION_KEY", encryption_key)

    with pytest.raises(RuntimeError, match="API_KEY_ENCRYPTION_KEY") as error:
        key_vault_service.encrypt_secret(secret)

    assert secret not in str(error.value)
