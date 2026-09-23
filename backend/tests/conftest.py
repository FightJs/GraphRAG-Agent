"""
conftest.py — 测试专用配置
使用临时文件 SQLite，所有连接共享同一数据库（包括后台任务）
"""
import os
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from cryptography.fernet import Fernet

# ── 在导入 app 之前覆盖数据库 URL 为临时文件 ────────────────────────────
_TEST_DB = "./test_temp_graphrag.db"
os.environ["API_KEY_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
import app.config as _cfg
_cfg.settings.DATABASE_URL = f"sqlite+aiosqlite:///{_TEST_DB}"
# 测试环境始终使用 mock 管线，不消耗真实 LLM 额度，也不依赖真实文件解析
_cfg.settings.DEEPSEEK_API_KEY = ""
_cfg.settings.MOCK_EXTERNAL_SERVICES = True

from app.database import engine, AsyncSessionLocal, Base, get_db, init_db
from app.main import app

async def _override_get_db():
    async with AsyncSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = _override_get_db

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    """创建所有表，测试结束后清理"""
    # 确保使用最新的 engine（已指向 test db）
    async with engine.begin() as conn:
        from app.models import db_models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)

@pytest.fixture(scope="session")
async def client(setup_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


TEST_USER = {"username": "testuser01", "email": "test01@graphrag.test", "password": "TestPass123"}


@pytest.fixture(scope="session")
async def auth_headers(client, setup_db):
    """注册并登录，返回 Authorization 头；同时预置 provider key 以通过 readiness 检查"""
    from app.services import key_vault_service

    await client.post("/api/v2/auth/register", json=TEST_USER)
    resp = await client.post(
        "/api/v2/auth/login",
        json={"email": TEST_USER["email"], "password": TEST_USER["password"]},
    )
    if resp.status_code != 200:
        # 幂等：用户已存在时重新登录仍应成功
        assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    me = await client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {token}"})
    async with AsyncSessionLocal() as db:
        for provider in ("deepseek", "mineru", "embedding"):
            await key_vault_service.store_verified_key(
                db, me.json()["data"]["user_id"], provider, f"test-{provider}-credential"
            )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
async def kb_id(client, auth_headers):
    """创建知识库，返回 kb_id"""
    resp = await client.post(
        "/api/v2/kbs",
        json={"name": "测试知识库", "description": "接口测试用", "color": "blue"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()["data"]["kb_id"]
