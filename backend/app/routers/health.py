from fastapi import APIRouter, Depends
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.models.db_models import Document, User, QARecord
from app.schemas.common import Resp
from app.services import key_vault_service, vector_store
from app.dependencies import get_current_user
from app.models.db_models import User as UserModel

router = APIRouter(prefix="/api/v1", tags=["health"])

@router.get("/health")
async def health():
    return {"code": 0, "data": {"status": "ok", "version": "2.0.0", "timestamp": datetime.utcnow().isoformat() + "Z"}}

sys_router = APIRouter(prefix="/api/v2/system", tags=["system"])

@sys_router.get("/status")
async def system_status(
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # DB stats
    doc_total = (await db.execute(select(func.count(Document.doc_id)))).scalar() or 0
    doc_indexed = (await db.execute(select(func.count(Document.doc_id)).where(Document.status == "indexed"))).scalar() or 0
    doc_failed = (await db.execute(select(func.count(Document.doc_id)).where(Document.status == "failed"))).scalar() or 0
    doc_indexing = (await db.execute(select(func.count(Document.doc_id)).where(Document.status == "indexing"))).scalar() or 0
    user_total = (await db.execute(select(func.count(User.user_id)))).scalar() or 0
    qa_total = (await db.execute(select(func.count(QARecord.query_id)))).scalar() or 0

    # Provider key presence (no secrets)
    providers = {}
    for p in ("deepseek", "mineru", "embedding"):
        key = await key_vault_service.get_verified_secret_or_none(db, user.user_id, p)
        providers[p] = "verified" if key else "missing"

    # Storage dirs
    storage = {
        "upload_dir": settings.UPLOAD_DIR,
        "kg_dir": settings.KG_DIR,
        "chunks_dir": getattr(settings, "CHUNKS_DIR", ""),
        "milvus_uri": settings.MILVUS_URI,
    }

    # Vector store reachability (best-effort)
    vector_ok = True
    try:
        vector_store.ping() if hasattr(vector_store, "ping") else None
    except Exception:
        vector_ok = False

    return Resp.ok({
        "status": "ok",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "mock_external_services": settings.MOCK_EXTERNAL_SERVICES,
        "database": {"ok": True},
        "vector_store": {"ok": vector_ok, "uri": settings.MILVUS_URI},
        "storage": storage,
        "stats": {
            "docs_total": doc_total,
            "docs_indexed": doc_indexed,
            "docs_indexing": doc_indexing,
            "docs_failed": doc_failed,
            "users": user_total,
            "qa_records": qa_total,
        },
        "providers": providers,
    })

