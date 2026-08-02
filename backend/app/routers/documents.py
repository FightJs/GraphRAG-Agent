from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.common import Resp
from app.services import document_service
from app.dependencies import get_current_user
from app.models.db_models import User

router = APIRouter(tags=["documents"])

@router.post("/api/v1/documents/upload", status_code=201)
async def upload(
    file: UploadFile = File(...),
    kb_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        doc = await document_service.save_upload(db, file, user.user_id, kb_id)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(400, {"code": int(code), "msg": msg})
    return Resp.ok(_doc_dict(doc))

@router.post("/api/v2/documents/batch-upload", status_code=202)
async def batch_upload(
    files: list[UploadFile] = File(...),
    kb_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(files) > 10:
        raise HTTPException(400, {"code": 4007, "msg": "最多同时上传10个文件"})
    uploaded, failed = [], []
    for f in files:
        try:
            doc = await document_service.save_upload(db, f, user.user_id, kb_id)
            uploaded.append({"doc_id": doc.doc_id, "filename": doc.original_name, "status": "uploaded"})
        except ValueError as e:
            failed.append({"filename": f.filename, "error": str(e).split(":", 1)[-1]})
    return Resp.ok({"uploaded": uploaded, "failed": failed})

@router.get("/api/v1/documents")
async def list_docs(
    kb_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs = await document_service.list_docs(db, user.user_id, kb_id)
    return Resp.ok([_doc_dict(d) for d in docs])

@router.get("/api/v1/documents/{doc_id}")
async def get_doc(doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        doc = await document_service.get_doc(db, doc_id, user.user_id)
    except ValueError as e:
        raise HTTPException(404, {"code": 4041, "msg": str(e).split(":", 1)[-1]})
    return Resp.ok(_doc_dict(doc))

@router.delete("/api/v1/documents/{doc_id}")
async def delete_doc(doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await document_service.delete_doc(db, doc_id, user.user_id)
    except ValueError as e:
        raise HTTPException(404, {"code": 4041, "msg": str(e).split(":", 1)[-1]})
    return Resp.ok(msg="文档已删除")

def _doc_dict(doc) -> dict:
    return {
        "doc_id": doc.doc_id, "kb_id": doc.kb_id, "filename": doc.filename,
        "original_name": doc.original_name, "file_format": doc.file_format,
        "status": doc.status, "file_size": doc.file_size, "page_count": doc.page_count,
        "node_count": doc.node_count, "edge_count": doc.edge_count,
        "error_message": doc.error_message,
        "created_at": doc.created_at.isoformat() + "Z",
        "updated_at": doc.updated_at.isoformat() + "Z",
    }
