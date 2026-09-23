"""
通知偏好 / 站内通知 API 测试
"""
import pytest

from app.database import AsyncSessionLocal
from app.services import notification_service


class TestNotificationPreferences:
    async def test_get_default_preferences(self, client, auth_headers):
        r = await client.get("/api/v2/settings/notifications/preferences", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["index_completed"] is True
        assert data["index_failed"] is True
        assert data["qa_weekly_digest"] is True

    async def test_update_preferences(self, client, auth_headers):
        r = await client.put(
            "/api/v2/settings/notifications/preferences",
            json={"index_failed": False, "qa_weekly_digest": False},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["index_failed"] is False
        assert data["qa_weekly_digest"] is False
        assert data["index_completed"] is True

        r2 = await client.get("/api/v2/settings/notifications/preferences", headers=auth_headers)
        assert r2.json()["data"]["index_failed"] is False

        # restore defaults for other tests
        await client.put(
            "/api/v2/settings/notifications/preferences",
            json={"index_completed": True, "index_failed": True, "qa_weekly_digest": True},
            headers=auth_headers,
        )

    async def test_preferences_require_auth(self, client):
        r = await client.get("/api/v2/settings/notifications/preferences")
        assert r.status_code == 401


class TestNotifications:
    async def test_list_empty_ok(self, client, auth_headers):
        r = await client.get("/api/v2/notifications", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert "items" in data
        assert "unread" in data

    async def test_create_via_service_respects_preference(self, client, auth_headers):
        me = await client.get("/api/v2/auth/me", headers=auth_headers)
        user_id = me.json()["data"]["user_id"]

        # preference on → create
        async with AsyncSessionLocal() as db:
            await notification_service.update_preferences(db, user_id, {"index_completed": True})
            created = await notification_service.create_notification(
                db,
                user_id,
                notification_service.TYPE_INDEX_COMPLETED,
                title="索引完成",
                body="文档《demo.pdf》已完成索引。",
                related_id="doc-demo-1",
            )
            assert created is not None

        r = await client.get("/api/v2/notifications", headers=auth_headers)
        data = r.json()["data"]
        assert data["unread"] >= 1
        assert any(n["title"] == "索引完成" for n in data["items"])

        r2 = await client.get("/api/v2/notifications/unread-count", headers=auth_headers)
        assert r2.json()["data"]["unread"] >= 1

        # mark first unread as read
        target = next(n for n in data["items"] if not n["is_read"])
        r3 = await client.post(
            f"/api/v2/notifications/{target['notification_id']}/read", headers=auth_headers
        )
        assert r3.status_code == 200
        assert r3.json()["data"]["is_read"] is True

        # mark all read
        r4 = await client.post("/api/v2/notifications/read-all", headers=auth_headers)
        assert r4.status_code == 200
        r5 = await client.get("/api/v2/notifications/unread-count", headers=auth_headers)
        assert r5.json()["data"]["unread"] == 0

    async def test_preference_off_skips_create(self, client, auth_headers):
        me = await client.get("/api/v2/auth/me", headers=auth_headers)
        user_id = me.json()["data"]["user_id"]

        async with AsyncSessionLocal() as db:
            await notification_service.update_preferences(db, user_id, {"index_failed": False})
            skipped = await notification_service.create_notification(
                db,
                user_id,
                notification_service.TYPE_INDEX_FAILED,
                title="索引失败",
                body="should not create",
            )
            assert skipped is None
            await notification_service.update_preferences(db, user_id, {"index_failed": True})

    async def test_weekly_digest(self, client, auth_headers):
        me = await client.get("/api/v2/auth/me", headers=auth_headers)
        user_id = me.json()["data"]["user_id"]

        async with AsyncSessionLocal() as db:
            await notification_service.update_preferences(db, user_id, {"qa_weekly_digest": True})
            notif = await notification_service.generate_weekly_qa_digest(db, user_id)
            assert notif is not None
            assert notif.type == "qa.weekly_digest"
            assert "问答" in notif.title

        r = await client.get("/api/v2/notifications", headers=auth_headers)
        assert any(n["type"] == "qa.weekly_digest" for n in r.json()["data"]["items"])

    async def test_delete_notification(self, client, auth_headers):
        me = await client.get("/api/v2/auth/me", headers=auth_headers)
        user_id = me.json()["data"]["user_id"]

        async with AsyncSessionLocal() as db:
            notif = await notification_service.create_notification(
                db,
                user_id,
                notification_service.TYPE_INDEX_COMPLETED,
                title="待删除通知",
                body="temp",
                force=True,
            )
            assert notif is not None
            nid = notif.notification_id

        r = await client.delete(f"/api/v2/notifications/{nid}", headers=auth_headers)
        assert r.status_code == 200
        r2 = await client.post(f"/api/v2/notifications/{nid}/read", headers=auth_headers)
        assert r2.status_code == 404

    async def test_index_event_creates_notification(self, client, auth_headers, kb_id):
        """启动真实索引后应产生站内通知（默认偏好开启）"""
        import asyncio
        import io

        pdf_content = b"%PDF-1.4 notify test document for graphrag"
        r = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("notify_test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            data={"kb_id": kb_id},
            headers=auth_headers,
        )
        assert r.status_code == 201
        doc_id = r.json()["data"]["doc_id"]

        me = await client.get("/api/v2/auth/me", headers=auth_headers)
        user_id = me.json()["data"]["user_id"]
        async with AsyncSessionLocal() as db:
            await notification_service.update_preferences(
                db, user_id, {"index_completed": True, "index_failed": True}
            )

        resp = await client.post(f"/api/v1/documents/{doc_id}/index", headers=auth_headers)
        assert resp.status_code == 202
        task_id = resp.json()["data"]["task_id"]

        for _ in range(60):
            await asyncio.sleep(0.5)
            r2 = await client.get(f"/api/v1/index/tasks/{task_id}", headers=auth_headers)
            if r2.json()["data"]["status"] in ("indexed", "failed"):
                break

        # allow notify hook to finish commit
        await asyncio.sleep(0.3)
        r3 = await client.get("/api/v2/notifications", headers=auth_headers)
        items = r3.json()["data"]["items"]
        assert any(
            n["type"] in ("index.completed", "index.failed") and n.get("related_id") == doc_id
            for n in items
        ), f"expected index notification for {doc_id}, got: {items}"

    async def test_notifications_require_auth(self, client):
        r = await client.get("/api/v2/notifications")
        assert r.status_code == 401
