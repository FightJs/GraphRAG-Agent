"""
GraphRAG Agent Backend - 完整 API 接口测试套件
覆盖规范 v2.0 所有核心接口：Auth / KB / Documents / Index / KG / QA / Webhook
"""
import asyncio
import io
import time
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import AsyncSessionLocal
from app.services import key_vault_service

BASE = "http://test"

# ── 测试数据 ──────────────────────────────────────────────────────────
TEST_USER = {"username": "testuser01", "email": "test01@graphrag.test", "password": "TestPass123"}
TEST_USER2 = {"username": "testuser02", "email": "test02@graphrag.test", "password": "TestPass456"}

# ── fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        yield c

@pytest.fixture(scope="session")
async def auth_headers(client):
    """注册并登录，返回 Authorization 头"""
    await client.post("/api/v2/auth/register", json=TEST_USER)
    resp = await client.post("/api/v2/auth/login", json={"email": TEST_USER["email"], "password": TEST_USER["password"]})
    assert resp.status_code == 200
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
    resp = await client.post("/api/v2/kbs", json={"name": "测试知识库", "description": "接口测试用", "color": "blue"}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["data"]["kb_id"]

@pytest.fixture(scope="session")
async def doc_id(client, auth_headers, kb_id):
    """上传测试文档，返回 doc_id"""
    pdf_content = b"%PDF-1.4 mock content for testing graphrag pipeline"
    resp = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("test_resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
        data={"kb_id": kb_id},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()["data"]["doc_id"]

@pytest.fixture(scope="session")
async def indexed_doc_id(client, auth_headers, kb_id):
    """上传独立文档，启动索引并等待完成，返回已索引的 doc_id"""
    pdf_content = b"%PDF-1.4 indexed doc for kg and qa tests"
    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("indexed_resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
        data={"kb_id": kb_id},
        headers=auth_headers,
    )
    assert r.status_code == 201
    new_doc_id = r.json()["data"]["doc_id"]

    resp = await client.post(f"/api/v1/documents/{new_doc_id}/index", headers=auth_headers)
    assert resp.status_code == 202, f"启动索引失败: {resp.text}"
    task_id = resp.json()["data"]["task_id"]

    # 轮询等待索引完成（最多 30s）
    for _ in range(60):
        await asyncio.sleep(0.5)
        r2 = await client.get(f"/api/v1/index/tasks/{task_id}", headers=auth_headers)
        status = r2.json()["data"]["status"]
        if status in ("indexed", "failed"):
            break
    return new_doc_id


# ════════════════════════════════════════════════════════════════════
# § 1  Health
# ════════════════════════════════════════════════════════════════════
class TestHealth:
    async def test_health(self, client):
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "ok"


# ════════════════════════════════════════════════════════════════════
# § 2  Auth
# ════════════════════════════════════════════════════════════════════
class TestAuth:
    async def test_register_success(self, client):
        r = await client.post("/api/v2/auth/register", json=TEST_USER2)
        assert r.status_code in (200, 201, 409)  # 409 = already registered

    async def test_register_duplicate_email(self, client):
        await client.post("/api/v2/auth/register", json=TEST_USER)
        r = await client.post("/api/v2/auth/register", json=TEST_USER)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == 4092

    async def test_register_weak_password(self, client):
        bad = {"username": "weakpwd", "email": "weak@test.com", "password": "short"}
        r = await client.post("/api/v2/auth/register", json=bad)
        assert r.status_code == 422

    async def test_login_success(self, client):
        r = await client.post("/api/v2/auth/login", json={"email": TEST_USER["email"], "password": TEST_USER["password"]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "access_token" in data
        assert data["token_type"] == "Bearer"

    async def test_login_wrong_password(self, client):
        r = await client.post("/api/v2/auth/login", json={"email": TEST_USER["email"], "password": "WrongPass999"})
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == 4011

    async def test_me(self, client, auth_headers):
        r = await client.get("/api/v2/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["email"] == TEST_USER["email"]

    async def test_logout(self, client, auth_headers):
        r = await client.post("/api/v2/auth/logout", headers=auth_headers)
        assert r.status_code == 200


# ════════════════════════════════════════════════════════════════════
# § 3  Knowledge Base CRUD
# ════════════════════════════════════════════════════════════════════
class TestKnowledgeBase:
    async def test_create_kb(self, client, auth_headers):
        r = await client.post("/api/v2/kbs", json={"name": "简历库-临时", "color": "purple"}, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()["data"]
        assert "kb_id" in data
        assert data["color"] == "purple"
        return data["kb_id"]

    async def test_create_kb_duplicate(self, client, auth_headers):
        await client.post("/api/v2/kbs", json={"name": "重复名称测试"}, headers=auth_headers)
        r = await client.post("/api/v2/kbs", json={"name": "重复名称测试"}, headers=auth_headers)
        assert r.status_code == 409

    async def test_list_kbs(self, client, auth_headers):
        r = await client.get("/api/v2/kbs", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()["data"]["items"], list)

    async def test_get_kb(self, client, auth_headers, kb_id):
        r = await client.get(f"/api/v2/kbs/{kb_id}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["kb_id"] == kb_id

    async def test_get_kb_not_found(self, client, auth_headers):
        r = await client.get("/api/v2/kbs/nonexistent-id", headers=auth_headers)
        assert r.status_code == 404

    async def test_update_kb(self, client, auth_headers, kb_id):
        r = await client.patch(f"/api/v2/kbs/{kb_id}", json={"name": "更新后知识库", "color": "green"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["color"] == "green"

    async def test_kb_requires_auth(self, client):
        r = await client.get("/api/v2/kbs")
        assert r.status_code == 401


# ════════════════════════════════════════════════════════════════════
# § 4  Documents
# ════════════════════════════════════════════════════════════════════
class TestDocuments:
    async def test_upload_pdf(self, client, auth_headers, kb_id):
        content = b"%PDF-1.4 another test document"
        r = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc_upload_test.pdf", io.BytesIO(content), "application/pdf")},
            data={"kb_id": kb_id},
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["status"] == "uploaded"
        assert data["file_format"] == "PDF"

    async def test_upload_unsupported_format(self, client, auth_headers):
        r = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("bad.exe", io.BytesIO(b"binary"), "application/octet-stream")},
            headers=auth_headers,
        )
        assert r.status_code == 400

    async def test_batch_upload(self, client, auth_headers, kb_id):
        files = [
            ("files", ("resume_a.pdf", io.BytesIO(b"%PDF-1.4 resume A"), "application/pdf")),
            ("files", ("resume_b.pdf", io.BytesIO(b"%PDF-1.4 resume B"), "application/pdf")),
        ]
        r = await client.post("/api/v2/documents/batch-upload", files=files, data={"kb_id": kb_id}, headers=auth_headers)
        assert r.status_code == 202
        data = r.json()["data"]
        assert len(data["uploaded"]) == 2
        assert data["failed"] == []

    async def test_list_documents(self, client, auth_headers, kb_id):
        r = await client.get(f"/api/v1/documents?kb_id={kb_id}", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    async def test_get_document(self, client, auth_headers, doc_id):
        r = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["doc_id"] == doc_id

    async def test_delete_document(self, client, auth_headers, kb_id):
        # 上传再删除
        content = b"%PDF-1.4 to be deleted"
        r = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("delete_me.pdf", io.BytesIO(content), "application/pdf")},
            data={"kb_id": kb_id},
            headers=auth_headers,
        )
        tmp_id = r.json()["data"]["doc_id"]
        r2 = await client.delete(f"/api/v1/documents/{tmp_id}", headers=auth_headers)
        assert r2.status_code == 200


# ════════════════════════════════════════════════════════════════════
# § 5  Index Pipeline
# ════════════════════════════════════════════════════════════════════
class TestIndexPipeline:
    async def test_start_index(self, client, auth_headers, doc_id):
        r = await client.post(f"/api/v1/documents/{doc_id}/index", headers=auth_headers)
        # 可能已在索引中（409）或启动成功（202）
        assert r.status_code in (202, 400)

    async def test_index_pipeline_completes(self, client, auth_headers, indexed_doc_id):
        """等待索引完成并验证文档状态"""
        r = await client.get(f"/api/v1/documents/{indexed_doc_id}", headers=auth_headers)
        assert r.status_code == 200
        doc = r.json()["data"]
        assert doc["status"] == "indexed"
        assert doc["node_count"] > 0
        assert doc["edge_count"] > 0

    async def test_get_task_status(self, client, auth_headers, kb_id):
        # 上传独立文档并启动索引来测试 task 查询，不影响 indexed_doc_id
        content = b"%PDF-1.4 task status test doc"
        r0 = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("task_test.pdf", io.BytesIO(content), "application/pdf")},
            data={"kb_id": kb_id},
            headers=auth_headers,
        )
        tmp_id = r0.json()["data"]["doc_id"]
        r = await client.post(f"/api/v1/documents/{tmp_id}/index", headers=auth_headers)
        assert r.status_code == 202
        task_id = r.json()["data"]["task_id"]
        r2 = await client.get(f"/api/v1/index/tasks/{task_id}", headers=auth_headers)
        assert r2.status_code == 200
        assert "progress" in r2.json()["data"]

    async def test_batch_index(self, client, auth_headers, kb_id):
        """批量启动索引"""
        # 先上传两个文档
        ids = []
        for i in range(2):
            content = f"%PDF-1.4 batch doc {i}".encode()
            r = await client.post(
                "/api/v1/documents/upload",
                files={"file": (f"batch_{i}.pdf", io.BytesIO(content), "application/pdf")},
                data={"kb_id": kb_id},
                headers=auth_headers,
            )
            ids.append(r.json()["data"]["doc_id"])
        r = await client.post("/api/v2/index/batch", json={"doc_ids": ids}, headers=auth_headers)
        assert r.status_code == 202
        assert len(r.json()["data"]["tasks"]) == 2


# ════════════════════════════════════════════════════════════════════
# § 6  Knowledge Graph
# ════════════════════════════════════════════════════════════════════
class TestKnowledgeGraph:
    async def test_get_kg(self, client, auth_headers, indexed_doc_id):
        r = await client.get(f"/api/v1/kg/{indexed_doc_id}", headers=auth_headers)
        assert r.status_code == 200
        kg = r.json()["data"]
        assert "nodes" in kg
        assert "edges" in kg
        assert "meta" in kg
        assert kg["meta"]["total_nodes"] > 0

    async def test_kg_not_indexed(self, client, auth_headers, doc_id):
        """未索引文档获取 KG 应返回错误"""
        # 上传新文档但不索引
        content = b"%PDF-1.4 not indexed"
        r = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("noindex.pdf", io.BytesIO(content), "application/pdf")},
            headers=auth_headers,
        )
        new_id = r.json()["data"]["doc_id"]
        r2 = await client.get(f"/api/v1/kg/{new_id}", headers=auth_headers)
        assert r2.status_code in (400, 404)

    async def test_kg_edit_add_node(self, client, auth_headers, indexed_doc_id):
        operations = [{"op": "add_node", "node": {"id": "test_node_rust", "label": "Rust", "type": "SKILL", "attributes": {"level": "学习中"}}}]
        r = await client.patch(f"/api/v2/kg/{indexed_doc_id}", json={"operations": operations}, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["applied_ops"] == 1
        assert data["skipped_ops"] == 0

    async def test_kg_edit_duplicate_node(self, client, auth_headers, indexed_doc_id):
        """重复添加同一节点应被 skip"""
        operations = [{"op": "add_node", "node": {"id": "test_node_rust", "label": "Rust", "type": "SKILL", "attributes": {}}}]
        r = await client.patch(f"/api/v2/kg/{indexed_doc_id}", json={"operations": operations}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["skipped_ops"] == 1

    async def test_kg_edit_delete_node(self, client, auth_headers, indexed_doc_id):
        operations = [{"op": "delete_node", "node_id": "test_node_rust"}]
        r = await client.patch(f"/api/v2/kg/{indexed_doc_id}", json={"operations": operations}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["applied_ops"] == 1

    async def test_kg_edit_invalid_op(self, client, auth_headers, indexed_doc_id):
        operations = [{"op": "invalid_operation"}]
        r = await client.patch(f"/api/v2/kg/{indexed_doc_id}", json={"operations": operations}, headers=auth_headers)
        assert r.status_code == 422


# ════════════════════════════════════════════════════════════════════
# § 7  Q&A
# ════════════════════════════════════════════════════════════════════
class TestQA:
    async def test_qa_sync(self, client, auth_headers, indexed_doc_id):
        payload = {"doc_id": indexed_doc_id, "question": "候选人有哪些核心技能？", "stream": False,
                   "options": {"retrieval_mode": "kg_only"}}
        r = await client.post("/api/v1/qa/query", json=payload, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert "query_id" in data
        assert len(data["answer"]) > 0
        assert "token_usage" in data

    async def test_qa_stream(self, client, auth_headers, indexed_doc_id):
        payload = {"doc_id": indexed_doc_id, "question": "他在哪家公司工作？", "stream": True,
                   "options": {"retrieval_mode": "kg_only"}}
        async with client.stream("POST", "/api/v1/qa/query", json=payload, headers=auth_headers) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            events = []
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                if "done" in events:
                    break
        assert "delta" in events
        assert "done" in events

    async def test_qa_history(self, client, auth_headers):
        r = await client.get("/api/v1/qa/history", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    async def test_qa_feedback_positive(self, client, auth_headers, indexed_doc_id):
        # 先问一个问题
        payload = {"doc_id": indexed_doc_id, "question": "教育背景？", "stream": False}
        r = await client.post("/api/v1/qa/query", json=payload, headers=auth_headers)
        query_id = r.json()["data"]["query_id"]
        # 提交反馈
        r2 = await client.post(f"/api/v2/qa/{query_id}/feedback",
                                json={"rating": "positive", "comment": "回答准确"},
                                headers=auth_headers)
        assert r2.status_code == 201
        assert r2.json()["data"]["rating"] == "positive"

    async def test_qa_feedback_duplicate(self, client, auth_headers, indexed_doc_id):
        payload = {"doc_id": indexed_doc_id, "question": "技能列表？", "stream": False}
        r = await client.post("/api/v1/qa/query", json=payload, headers=auth_headers)
        query_id = r.json()["data"]["query_id"]
        await client.post(f"/api/v2/qa/{query_id}/feedback", json={"rating": "positive"}, headers=auth_headers)
        r2 = await client.post(f"/api/v2/qa/{query_id}/feedback", json={"rating": "negative"}, headers=auth_headers)
        assert r2.status_code == 409
        assert r2.json()["detail"]["code"] == 4093

    async def test_kb_qa(self, client, auth_headers, indexed_doc_id, kb_id):
        payload = {"kb_id": kb_id, "doc_ids": [indexed_doc_id], "question": "综合分析候选人", "stream": False,
                   "options": {"retrieval_mode": "hybrid"}}
        r = await client.post("/api/v2/qa/kb-query", json=payload, headers=auth_headers)
        assert r.status_code == 200

    async def test_kb_qa_too_many_docs(self, client, auth_headers, kb_id):
        payload = {"kb_id": kb_id, "doc_ids": [f"doc_{i}" for i in range(11)],
                   "question": "测试", "stream": False}
        r = await client.post("/api/v2/qa/kb-query", json=payload, headers=auth_headers)
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == 4007


# ════════════════════════════════════════════════════════════════════
# § 8  Webhooks
# ════════════════════════════════════════════════════════════════════
class TestWebhooks:
    async def test_create_webhook(self, client, auth_headers):
        r = await client.post("/api/v2/webhooks",
                              json={"url": "https://example.com/wh", "events": ["index.completed"], "secret": "my-secret"},
                              headers=auth_headers)
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["url"] == "https://example.com/wh"
        assert "index.completed" in data["events"]
        return data["webhook_id"]

    async def test_create_webhook_invalid_event(self, client, auth_headers):
        r = await client.post("/api/v2/webhooks",
                              json={"url": "https://example.com/wh2", "events": ["unknown.event"]},
                              headers=auth_headers)
        assert r.status_code == 400

    async def test_list_webhooks(self, client, auth_headers):
        r = await client.get("/api/v2/webhooks", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    async def test_delete_webhook(self, client, auth_headers):
        r = await client.post("/api/v2/webhooks",
                              json={"url": "https://example.com/delete-wh", "events": ["index.failed"]},
                              headers=auth_headers)
        wh_id = r.json()["data"]["webhook_id"]
        r2 = await client.delete(f"/api/v2/webhooks/{wh_id}", headers=auth_headers)
        assert r2.status_code == 200
        r3 = await client.get(f"/api/v2/webhooks/{wh_id}", headers=auth_headers)
        assert r3.status_code == 404

    async def test_webhook_requires_auth(self, client):
        r = await client.get("/api/v2/webhooks")
        assert r.status_code == 401
