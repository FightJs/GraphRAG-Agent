from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.db_models import KnowledgeBase, Document
from app.schemas.kb import KBCreate, KBUpdate
import uuid
from datetime import datetime

async def create_kb(db: AsyncSession, owner_id: str, data: KBCreate) -> KnowledgeBase:
    existing = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.owner_id == owner_id, KnowledgeBase.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise ValueError("4092:该知识库名称已存在")
    kb = KnowledgeBase(kb_id=str(uuid.uuid4()), owner_id=owner_id, **data.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb

async def list_kbs(db: AsyncSession, owner_id: str) -> list[KnowledgeBase]:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.owner_id == owner_id).order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars().all())

async def get_kb(db: AsyncSession, kb_id: str, owner_id: str) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id, KnowledgeBase.owner_id == owner_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise ValueError("4044:知识库不存在")
    return kb

async def update_kb(db: AsyncSession, kb_id: str, owner_id: str, data: KBUpdate) -> KnowledgeBase:
    kb = await get_kb(db, kb_id, owner_id)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(kb, k, v)
    kb.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(kb)
    return kb

async def delete_kb(db: AsyncSession, kb_id: str, owner_id: str) -> int:
    kb = await get_kb(db, kb_id, owner_id)
    result = await db.execute(select(func.count()).select_from(Document).where(Document.kb_id == kb_id))
    doc_count = result.scalar() or 0
    await db.delete(kb)
    await db.commit()
    return doc_count

async def get_kb_stats(db: AsyncSession, kb_id: str) -> dict:
    docs = await db.execute(select(Document).where(Document.kb_id == kb_id))
    docs_list = list(docs.scalars().all())
    total_nodes = sum(d.node_count for d in docs_list)
    total_edges = sum(d.edge_count for d in docs_list)
    indexed = sum(1 for d in docs_list if d.status == "indexed")
    return {"doc_count": len(docs_list), "indexed_count": indexed, "total_nodes": total_nodes, "total_edges": total_edges}
