from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.kb import KBCreate, KBUpdate
from app.schemas.common import Resp
from app.services import kb_service
from app.dependencies import get_current_user
from app.models.db_models import User

router = APIRouter(prefix="/api/v2/kbs", tags=["kbs"])

def _kb_dict(kb, stats: dict) -> dict:
    return {
        "kb_id": kb.kb_id,
        "name": kb.name,
        "description": kb.description,
        "color": kb.color,
        "owner_id": kb.owner_id,
        "doc_count": stats.get("doc_count", 0),
        "indexed_count": stats.get("indexed_count", 0),
        "total_nodes": stats.get("total_nodes", 0),
        "total_edges": stats.get("total_edges", 0),
        "created_at": kb.created_at.isoformat() + "Z",
        "updated_at": kb.updated_at.isoformat() + "Z",
    }

@router.post("", status_code=201)
async def create_kb(body: KBCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        kb = await kb_service.create_kb(db, user.user_id, body)
    except ValueError as e:
        parts = str(e).split(":", 1)
        raise HTTPException(409, {"code": int(parts[0]), "msg": parts[1]})
    stats = await kb_service.get_kb_stats(db, kb.kb_id)
    return Resp.ok(_kb_dict(kb, stats))

@router.get("")
async def list_kbs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kbs = await kb_service.list_kbs(db, user.user_id)
    items = []
    for kb in kbs:
        stats = await kb_service.get_kb_stats(db, kb.kb_id)
        items.append(_kb_dict(kb, stats))
    return Resp.ok({"items": items, "total": len(items)})

@router.get("/{kb_id}")
async def get_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        kb = await kb_service.get_kb(db, kb_id, user.user_id)
    except ValueError as e:
        parts = str(e).split(":", 1)
        raise HTTPException(404, {"code": int(parts[0]), "msg": parts[1]})
    stats = await kb_service.get_kb_stats(db, kb.kb_id)
    return Resp.ok(_kb_dict(kb, stats))

@router.patch("/{kb_id}")
async def update_kb(kb_id: str, body: KBUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        kb = await kb_service.update_kb(db, kb_id, user.user_id, body)
    except ValueError as e:
        parts = str(e).split(":", 1)
        raise HTTPException(404, {"code": int(parts[0]), "msg": parts[1]})
    stats = await kb_service.get_kb_stats(db, kb.kb_id)
    return Resp.ok(_kb_dict(kb, stats))

@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        deleted_docs = await kb_service.delete_kb(db, kb_id, user.user_id)
    except ValueError as e:
        parts = str(e).split(":", 1)
        raise HTTPException(404, {"code": int(parts[0]), "msg": parts[1]})
    return Resp.ok({"kb_id": kb_id, "deleted_docs": deleted_docs}, msg="知识库及全部文档已删除")
