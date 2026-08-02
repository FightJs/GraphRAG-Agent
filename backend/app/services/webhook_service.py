import json, uuid, hmac, hashlib
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.db_models import Webhook, WebhookDelivery

async def create_webhook(db: AsyncSession, owner_id: str, url: str, events: list[str], secret: str | None = None) -> Webhook:
    wh = Webhook(
        webhook_id=str(uuid.uuid4()),
        owner_id=owner_id,
        url=url,
        events_json=json.dumps(events),
        secret_plain=secret,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest() if secret else None,
    )
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    return wh

async def list_webhooks(db: AsyncSession, owner_id: str) -> list[Webhook]:
    result = await db.execute(select(Webhook).where(Webhook.owner_id == owner_id))
    return list(result.scalars().all())

async def get_webhook(db: AsyncSession, webhook_id: str, owner_id: str) -> Webhook:
    result = await db.execute(select(Webhook).where(Webhook.webhook_id == webhook_id, Webhook.owner_id == owner_id))
    wh = result.scalar_one_or_none()
    if not wh:
        raise ValueError("4044:Webhook不存在")
    return wh

async def delete_webhook(db: AsyncSession, webhook_id: str, owner_id: str):
    wh = await get_webhook(db, webhook_id, owner_id)
    await db.delete(wh)
    await db.commit()

async def dispatch_event(db: AsyncSession, owner_id: str, event: str, data: dict):
    """向订阅了该事件的所有 Webhook 投递通知"""
    result = await db.execute(select(Webhook).where(Webhook.owner_id == owner_id, Webhook.is_active == True))
    webhooks = list(result.scalars().all())
    payload = {"event": event, "timestamp": datetime.utcnow().isoformat() + "Z", "data": data}
    for wh in webhooks:
        events = json.loads(wh.events_json)
        if event not in events:
            continue
        delivery = WebhookDelivery(
            delivery_id=str(uuid.uuid4()),
            webhook_id=wh.webhook_id,
            event=event,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        db.add(delivery)
        await db.commit()
        # 异步发送（不阻塞）
        import asyncio
        asyncio.create_task(_send(wh.url, payload, wh.secret_plain, delivery.delivery_id))

async def _send(url: str, payload: dict, secret: str | None, delivery_id: str):
    import httpx
    headers = {"Content-Type": "application/json"}
    if secret:
        sig = hmac.new(secret.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()
        headers["X-GraphRAG-Signature"] = f"sha256={sig}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload, headers=headers)
    except Exception:
        pass  # 静默失败，生产环境应实现重试逻辑
