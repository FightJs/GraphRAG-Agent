import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.webhook import WebhookCreate, WebhookUpdate
from app.schemas.common import Resp
from app.services import webhook_service
from app.dependencies import get_current_user
from app.models.db_models import User

router = APIRouter(prefix="/api/v2/webhooks", tags=["webhooks"])

@router.post("", status_code=201)
async def create_webhook(body: WebhookCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    valid_events = {"index.completed", "index.failed"}
    for e in body.events:
        if e not in valid_events:
            raise HTTPException(400, {"code": 4001, "msg": f"不支持的事件类型: {e}"})
    wh = await webhook_service.create_webhook(db, user.user_id, body.url, body.events, body.secret)
    return Resp.ok(_wh_dict(wh))

@router.get("")
async def list_webhooks(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    whs = await webhook_service.list_webhooks(db, user.user_id)
    return Resp.ok([_wh_dict(w) for w in whs])

@router.get("/{webhook_id}")
async def get_webhook(webhook_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        wh = await webhook_service.get_webhook(db, webhook_id, user.user_id)
    except ValueError as e:
        raise HTTPException(404, {"code": 4044, "msg": str(e).split(":", 1)[-1]})
    return Resp.ok(_wh_dict(wh))

@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await webhook_service.delete_webhook(db, webhook_id, user.user_id)
    except ValueError as e:
        raise HTTPException(404, {"code": 4044, "msg": str(e).split(":", 1)[-1]})
    return Resp.ok(msg="Webhook已删除")

def _wh_dict(wh) -> dict:
    return {
        "webhook_id": wh.webhook_id, "url": wh.url,
        "events": json.loads(wh.events_json), "is_active": wh.is_active,
        "created_at": wh.created_at.isoformat() + "Z",
    }
