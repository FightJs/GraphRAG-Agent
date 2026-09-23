import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Notification, NotificationPreference, QARecord

DEFAULT_PREFS = {
    "index_completed": True,
    "index_failed": True,
    "qa_weekly_digest": True,
}

TYPE_INDEX_COMPLETED = "index.completed"
TYPE_INDEX_FAILED = "index.failed"
TYPE_QA_WEEKLY_DIGEST = "qa.weekly_digest"

_TYPE_TO_PREF = {
    TYPE_INDEX_COMPLETED: "index_completed",
    TYPE_INDEX_FAILED: "index_failed",
    TYPE_QA_WEEKLY_DIGEST: "qa_weekly_digest",
}


async def get_preferences(db: AsyncSession, user_id: str) -> NotificationPreference:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()
    if pref:
        return pref
    pref = NotificationPreference(pref_id=str(uuid.uuid4()), user_id=user_id, **DEFAULT_PREFS)
    db.add(pref)
    await db.commit()
    await db.refresh(pref)
    return pref


async def update_preferences(db: AsyncSession, user_id: str, patch: dict) -> NotificationPreference:
    pref = await get_preferences(db, user_id)
    for key, value in patch.items():
        if value is None:
            continue
        if key not in DEFAULT_PREFS:
            raise ValueError(f"4001:不支持的通知偏好项: {key}")
        setattr(pref, key, bool(value))
    await db.commit()
    await db.refresh(pref)
    return pref


def prefs_to_dict(pref: NotificationPreference) -> dict:
    return {
        "index_completed": pref.index_completed,
        "index_failed": pref.index_failed,
        "qa_weekly_digest": pref.qa_weekly_digest,
    }


async def is_enabled(db: AsyncSession, user_id: str, notif_type: str) -> bool:
    pref = await get_preferences(db, user_id)
    field = _TYPE_TO_PREF.get(notif_type)
    if not field:
        return False
    return bool(getattr(pref, field))


async def create_notification(
    db: AsyncSession,
    user_id: str,
    notif_type: str,
    title: str,
    body: str = "",
    related_id: str | None = None,
    force: bool = False,
) -> Notification | None:
    """按用户偏好创建站内通知；force=True 时忽略偏好（测试/系统消息）。"""
    if not force and not await is_enabled(db, user_id, notif_type):
        return None
    notif = Notification(
        notification_id=str(uuid.uuid4()),
        user_id=user_id,
        type=notif_type,
        title=title,
        body=body,
        related_id=related_id,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return notif


async def notify_index_event(
    db: AsyncSession,
    user_id: str,
    *,
    doc_id: str,
    task_id: str,
    filename: str,
    success: bool,
    error: str | None = None,
    node_count: int | None = None,
) -> Notification | None:
    if success:
        body = f"文档《{filename}》已完成索引。"
        if node_count is not None:
            body += f"知识图谱节点数：{node_count}。"
        return await create_notification(
            db,
            user_id,
            TYPE_INDEX_COMPLETED,
            title="索引完成",
            body=body,
            related_id=doc_id,
        )
    body = f"文档《{filename}》索引失败。{error or ''}".strip()
    return await create_notification(
        db,
        user_id,
        TYPE_INDEX_FAILED,
        title="索引失败",
        body=body,
        related_id=doc_id,
    )


async def generate_weekly_qa_digest(db: AsyncSession, user_id: str) -> Notification | None:
    """生成本周问答统计摘要（由定时任务或测试触发）。"""
    if not await is_enabled(db, user_id, TYPE_QA_WEEKLY_DIGEST):
        return None
    since = datetime.utcnow() - timedelta(days=7)
    result = await db.execute(
        select(func.count(QARecord.query_id)).where(
            QARecord.user_id == user_id, QARecord.created_at >= since
        )
    )
    count = result.scalar() or 0
    return await create_notification(
        db,
        user_id,
        TYPE_QA_WEEKLY_DIGEST,
        title="本周问答统计",
        body=f"过去 7 天共完成 {count} 次问答。",
        force=True,
    )


async def list_notifications(db: AsyncSession, user_id: str, limit: int = 20) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_notifications(db: AsyncSession, user_id: str) -> tuple[int, int]:
    total = (
        await db.execute(
            select(func.count(Notification.notification_id)).where(Notification.user_id == user_id)
        )
    ).scalar() or 0
    unread = (
        await db.execute(
            select(func.count(Notification.notification_id)).where(
                Notification.user_id == user_id, Notification.is_read == False  # noqa: E712
            )
        )
    ).scalar() or 0
    return int(total), int(unread)


async def mark_read(db: AsyncSession, user_id: str, notification_id: str) -> Notification:
    result = await db.execute(
        select(Notification).where(
            Notification.notification_id == notification_id, Notification.user_id == user_id
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise ValueError("4044:通知不存在")
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return notif


async def mark_all_read(db: AsyncSession, user_id: str) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def delete_notification(db: AsyncSession, user_id: str, notification_id: str) -> None:
    result = await db.execute(
        select(Notification).where(
            Notification.notification_id == notification_id, Notification.user_id == user_id
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise ValueError("4044:通知不存在")
    await db.delete(notif)
    await db.commit()


async def clear_all(db: AsyncSession, user_id: str) -> int:
    result = await db.execute(delete(Notification).where(Notification.user_id == user_id))
    await db.commit()
    return int(result.rowcount or 0)


def notification_to_dict(notif: Notification) -> dict:
    return {
        "notification_id": notif.notification_id,
        "type": notif.type,
        "title": notif.title,
        "body": notif.body,
        "related_id": notif.related_id,
        "is_read": notif.is_read,
        "created_at": notif.created_at.isoformat() + "Z",
    }
