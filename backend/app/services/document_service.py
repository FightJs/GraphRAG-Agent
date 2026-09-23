import os, uuid, shutil
from pathlib import Path
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import Document

ALLOWED_EXTS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".html", ".csv"}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB

async def save_upload(db: AsyncSession, file: UploadFile, owner_id: str, kb_id: str | None = None) -> Document:
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in ALLOWED_EXTS:
        raise ValueError(f"5001:不支持的文件格式 {suffix}")
    doc_id = str(uuid.uuid4())
    save_dir = Path(settings.UPLOAD_DIR) / doc_id
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / (doc_id + suffix)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("5002:文件超过200MB限制")
    with open(save_path, "wb") as f:
        f.write(content)
    doc = Document(
        doc_id=doc_id,
        kb_id=kb_id,
        owner_id=owner_id,
        filename=doc_id + suffix,
        original_name=file.filename or "unknown",
        file_format=suffix.lstrip(".").upper(),
        file_path=str(save_path),
        file_size=len(content),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc

async def list_docs(db: AsyncSession, owner_id: str, kb_id: str | None = None) -> list[Document]:
    q = select(Document).where(Document.owner_id == owner_id)
    if kb_id:
        q = q.where(Document.kb_id == kb_id)
    result = await db.execute(q.order_by(Document.created_at.desc()))
    return list(result.scalars().all())

async def get_doc(db: AsyncSession, doc_id: str, owner_id: str) -> Document:
    result = await db.execute(
        select(Document).where(Document.doc_id == doc_id, Document.owner_id == owner_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("4041:文档不存在")
    return doc

async def delete_doc(db: AsyncSession, doc_id: str, owner_id: str) -> None:
    doc = await get_doc(db, doc_id, owner_id)
    upload_dir = Path(settings.UPLOAD_DIR) / doc_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    media_dir = Path(settings.MEDIA_DIR) / doc_id
    if media_dir.exists():
        shutil.rmtree(media_dir)
    kg_file = Path(settings.KG_DIR) / f"{doc_id}.json"
    if kg_file.exists():
        kg_file.unlink()
    chunks_file = Path(settings.CHUNKS_DIR) / f"{doc_id}.json"
    if chunks_file.exists():
        chunks_file.unlink()
    await db.delete(doc)
    await db.commit()
