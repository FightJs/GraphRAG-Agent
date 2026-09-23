from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.db_models import User
from app.schemas.common import Resp
from app.schemas.notification import (
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
)
from app.services import notification_service

prefs_router = APIRouter(prefix="/api/v2/settings/notifications", tags=["notification-settings"])
notif_router = APIRouter(prefix="/api/v2/notifications", tags=["notifications"])


def _http_error(exc: ValueError, default_status: int = 400) -> HTTPException:
    text = str(exc)
    if ":" in text and text.split(":", 1)[0].isdigit():
        code, msg = text.split(":", 1)
        status = 404 if code.startswith("404") else default_status
        return HTTPException(status, {"code": int(code), "msg": msg})
    return HTTPException(default_status, {"code": 4001, "msg": text})


@prefs_router.get("/preferences")
async def get_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    pref = await notification_service.get_preferences(db, user.user_id)
    return Resp.ok(notification_service.prefs_to_dict(pref))


@prefs_router.put("/preferences")
async def update_preferences(
    body: NotificationPreferencesUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        pref = await notification_service.update_preferences(
            db,
            user.user_id,
            {
                "index_completed": body.index_completed,
                "index_failed": body.index_failed,
                "qa_weekly_digest": body.qa_weekly_digest,
            },
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    return Resp.ok(notification_service.prefs_to_dict(pref), msg="通知偏好已保存")


@notif_router.get("")
async def list_notifications(
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 100))
    items = await notification_service.list_notifications(db, user.user_id, limit=limit)
    total, unread = await notification_service.count_notifications(db, user.user_id)
    return Resp.ok({
        "items": [notification_service.notification_to_dict(n) for n in items],
        "total": total,
        "unread": unread,
    })


@notif_router.get("/unread-count")
async def unread_count(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _, unread = await notification_service.count_notifications(db, user.user_id)
    return Resp.ok({"unread": unread})


@notif_router.post("/read-all")
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = await notification_service.mark_all_read(db, user.user_id)
    return Resp.ok({"updated": count}, msg=f"已标记 {count} 条通知为已读")


@notif_router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        notif = await notification_service.mark_read(db, user.user_id, notification_id)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return Resp.ok(notification_service.notification_to_dict(notif))


@notif_router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await notification_service.delete_notification(db, user.user_id, notification_id)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return Resp.ok(msg="通知已删除")


@notif_router.delete("")
async def clear_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = await notification_service.clear_all(db, user.user_id)
    return Resp.ok({"deleted": count}, msg=f"已清空 {count} 条通知")
