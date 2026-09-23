import asyncio, json, logging, uuid, random
from datetime import datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import Document, IndexTask
from app.services import (
    parsing_service,
    kg_extraction,
    key_vault_service,
    mineru_service,
    table_service,
    image_service,
    media_store,
    notification_service,
    webhook_service,
    embedding_service,
    vector_store,
)

logger = logging.getLogger(__name__)

STAGES = [
    {"name": "parse",    "label": "文档解析"},
    {"name": "markdown", "label": "Markdown转换"},
    {"name": "chunk",    "label": "文本分块"},
    {"name": "kg",       "label": "KG实体抽取"},
    {"name": "vector",   "label": "向量化索引"},
]

def _chunks_path(doc_id: str) -> Path:
    return Path(settings.CHUNKS_DIR) / f"{doc_id}.json"


def _content_list_path(doc_id: str) -> Path:
    return Path(settings.CHUNKS_DIR) / f"{doc_id}.content_list.json"

def _kg_path(doc_id: str) -> Path:
    return Path(settings.KG_DIR) / f"{doc_id}.json"

def _mock_kg(doc_id: str, original_name: str) -> dict:
    """无 LLM API Key 时的占位知识图谱（demo / 测试环境使用）"""
    name_base = Path(original_name).stem
    nodes = [
        {"id": f"person_{doc_id[:8]}", "label": name_base, "type": "PERSON", "attributes": {"role": "候选人", "source": original_name}},
        {"id": "skill_python", "label": "Python", "type": "SKILL", "attributes": {"level": "熟练", "years": 3}},
        {"id": "skill_langchain", "label": "LangChain", "type": "SKILL", "attributes": {"level": "熟练", "years": 2}},
        {"id": "skill_fastapi", "label": "FastAPI", "type": "SKILL", "attributes": {"level": "熟练", "years": 2}},
        {"id": "skill_docker", "label": "Docker", "type": "SKILL", "attributes": {"level": "了解", "years": 1}},
        {"id": f"company_{doc_id[:6]}", "label": "某科技有限公司", "type": "COMPANY", "attributes": {"industry": "AI/互联网"}},
        {"id": f"project_{doc_id[:6]}", "label": "GraphRAG知识库系统", "type": "PROJECT", "attributes": {"role": "主导开发"}},
        {"id": f"school_{doc_id[:6]}", "label": "清华大学", "type": "SCHOOL", "attributes": {"degree": "硕士", "major": "计算机科学"}},
        {"id": f"pos_{doc_id[:6]}", "label": "后端工程师", "type": "POSITION", "attributes": {"level": "P6"}},
    ]
    edges = [
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": "skill_python", "relation": "掌握"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": "skill_langchain", "relation": "精通"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": "skill_fastapi", "relation": "熟悉"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": "skill_docker", "relation": "了解"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": f"company_{doc_id[:6]}", "relation": "就职于"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": f"project_{doc_id[:6]}", "relation": "主导"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": f"school_{doc_id[:6]}", "relation": "毕业于"},
        {"id": str(uuid.uuid4()), "source": f"person_{doc_id[:8]}", "target": f"pos_{doc_id[:6]}", "relation": "担任"},
    ]
    return {
        "doc_id": doc_id,
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
    }

async def start_index_task(db: AsyncSession, doc_id: str, owner_id: str) -> IndexTask:
    result = await db.execute(select(Document).where(Document.doc_id == doc_id, Document.owner_id == owner_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("4041:文档不存在")
    if doc.status == "indexing":
        raise ValueError("5003:文档正在索引中")
    doc.status = "indexing"
    stages = [{"name": s["name"], "label": s["label"], "status": "pending", "progress": 0} for s in STAGES]
    task = IndexTask(task_id=str(uuid.uuid4()), doc_id=doc_id, status="indexing", progress=0, stages_json=json.dumps(stages, ensure_ascii=False))
    db.add(task)
    await db.commit()
    await db.refresh(task)
    _cancelled_tasks.discard(task.task_id)
    asyncio.create_task(_run_pipeline(doc_id, task.task_id, doc.original_name, doc.file_path, doc.file_format, owner_id))
    return task

_cancelled_tasks: set[str] = set()

def _is_cancelled(task_id: str) -> bool:
    return task_id in _cancelled_tasks

async def cancel_task(db: AsyncSession, task_id: str, owner_id: str) -> dict:
    """请求取消索引任务：打标记，pipeline 在阶段边界自行中止。"""
    result = await db.execute(
        select(IndexTask).join(Document, IndexTask.doc_id == Document.doc_id).where(
            IndexTask.task_id == task_id, Document.owner_id == owner_id
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise ValueError("4041:任务不存在")
    if task.status not in {"indexing", "pending"}:
        raise ValueError("4003:任务已结束，无法取消")
    _cancelled_tasks.add(task_id)
    return {"task_id": task_id, "status": "cancelling"}

async def _finalize_cancel(db: AsyncSession, doc_id: str, task_id: str, owner_id: str | None = None, filename: str | None = None):
    _cancelled_tasks.discard(task_id)
    try:
        result = await db.execute(select(Document).where(Document.doc_id == doc_id))
        doc = result.scalar_one_or_none()
        if doc and doc.status == "indexing":
            doc.status = "cancelled"
        result = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
        task = result.scalar_one_or_none()
        if task and task.status in {"indexing", "pending"}:
            stages = json.loads(task.stages_json or "[]")
            for s in stages:
                if s.get("status") == "running":
                    s["status"] = "cancelled"
            task.stages_json = json.dumps(stages, ensure_ascii=False)
            task.status = "cancelled"
        await db.commit()
    except Exception:
        logger.exception("finalize cancel failed for task %s", task_id)

async def _advance_stage(db: AsyncSession, task_id: str, index: int) -> bool:
    if _is_cancelled(task_id):
        return False
    result = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
    task = result.scalar_one_or_none()
    if not task or task.status == "cancelled":
        return False
    stages = json.loads(task.stages_json)
    stages[index]["status"] = "done"
    stages[index]["progress"] = 100
    task.stages_json = json.dumps(stages, ensure_ascii=False)
    task.progress = int((index + 1) / len(STAGES) * 100)
    await db.commit()
    return True

async def _notify_index_result(
    db: AsyncSession,
    owner_id: str,
    *,
    doc_id: str,
    task_id: str,
    filename: str,
    success: bool,
    error: str | None = None,
    node_count: int | None = None,
):
    """索引结果：站内通知（按用户偏好）+ Webhook 投递"""
    try:
        await notification_service.notify_index_event(
            db,
            owner_id,
            doc_id=doc_id,
            task_id=task_id,
            filename=filename,
            success=success,
            error=error,
            node_count=node_count,
        )
        data = {
            "doc_id": doc_id,
            "task_id": task_id,
            "filename": filename,
        }
        if success:
            data["kg_nodes"] = node_count
            await webhook_service.dispatch_event(db, owner_id, "index.completed", data)
        else:
            data["error_code"] = 5004
            data["error_msg"] = error or "索引失败"
            await webhook_service.dispatch_event(db, owner_id, "index.failed", data)
    except Exception:
        logger.exception("notification/webhook dispatch failed for task %s", task_id)


async def _fail_task(db: AsyncSession, doc_id: str, task_id: str, message: str, owner_id: str | None = None, filename: str | None = None):
    result = await db.execute(select(Document).where(Document.doc_id == doc_id))
    doc = result.scalar_one_or_none()
    if doc:
        doc.status = "failed"
        doc.error_message = message
        filename = filename or doc.original_name
        await db.commit()
    result2 = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
    task = result2.scalar_one_or_none()
    if task:
        task.status = "failed"
        task.error_message = message
        await db.commit()
    if owner_id:
        await _notify_index_result(
            db,
            owner_id,
            doc_id=doc_id,
            task_id=task_id,
            filename=filename or doc_id,
            success=False,
            error=message,
        )

async def _run_pipeline(doc_id: str, task_id: str, original_name: str, file_path: str, file_format: str, owner_id: str):
    """5阶段索引 Pipeline（后台运行）。有 MinerU Key 时优先结构化解析，否则本地 extract_text。

    parse 阶段内部完成 media（表格 JSON / 图片落盘）；markdown/chunk 使用占位符。
    """
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            deepseek_key = await key_vault_service.get_verified_secret_or_none(db, owner_id, "deepseek")
            mineru_key = await key_vault_service.get_verified_secret_or_none(db, owner_id, "mineru")
            # OpenRouter Key（embedding provider）用于 VLM 路由/描述
            vlm_key = await key_vault_service.get_verified_secret_or_none(db, owner_id, "embedding")
            use_llm = not settings.MOCK_EXTERNAL_SERVICES
            is_pdf = (file_format or "").upper() == "PDF"

            content_list: list[dict] = []
            markdown_text = ""
            plain_text = ""
            page_count = 0
            zip_bytes: bytes | None = None
            table_records: list[dict] = []
            image_metas: list[dict] = []
            table_ids_by_block: dict[int, str] = {}
            image_ids_by_block: dict[int, str] = {}

            # Stage 0: parse — 优先 MinerU 结构化解析 + media 落盘；失败/无 Key 时回退本地 extract_text
            if use_llm:
                if mineru_key and is_pdf:
                    try:
                        parsed = await mineru_service.extract_pdf(mineru_key, file_path, filename=original_name)
                        content_list = parsed.get("content_list") or []
                        markdown_text = parsed.get("markdown") or ""
                        page_count = parsed.get("page_count") or 0
                        zip_bytes = parsed.get("zip_bytes")
                        if content_list:
                            _content_list_path(doc_id).parent.mkdir(parents=True, exist_ok=True)
                            _content_list_path(doc_id).write_text(
                                json.dumps(content_list, ensure_ascii=False), encoding="utf-8"
                            )
                    except Exception:
                        content_list = []
                        markdown_text = ""
                        zip_bytes = None
                if not content_list:
                    plain_text, page_count = parsing_service.extract_text(file_path, file_format)

                # media：表格 JSON + 图片资产/解析（可独立失败，不阻断索引）
                if content_list:
                    try:
                        table_records, _ = await table_service.process_tables(
                            doc_id, content_list, deepseek_key, original_name=original_name
                        )
                        t_seq = 0
                        for i, block in enumerate(content_list):
                            if isinstance(block, dict) and block.get("type") == "table":
                                table_ids_by_block[i] = table_service.make_table_id(doc_id, t_seq)
                                t_seq += 1
                    except Exception as table_exc:
                        logger.warning("table pipeline failed doc=%s: %s", doc_id, table_exc)
                        table_records = []
                        table_ids_by_block = {}
                    try:
                        image_metas = await image_service.process_images(
                            doc_id, content_list, zip_bytes, vlm_key, original_name=original_name
                        )
                        i_seq = 0
                        for i, block in enumerate(content_list):
                            if isinstance(block, dict) and block.get("type") == "image":
                                image_ids_by_block[i] = image_service.make_image_id(doc_id, i_seq)
                                i_seq += 1
                    except Exception as image_exc:
                        logger.warning("image pipeline failed doc=%s: %s", doc_id, image_exc)
                        image_metas = []
                        image_ids_by_block = {}
            else:
                await asyncio.sleep(random.uniform(0.3, 0.8))
            if not await _advance_stage(db, task_id, 0):
                if _is_cancelled(task_id):
                    await _finalize_cancel(db, doc_id, task_id, owner_id=owner_id, filename=original_name)
                return

            # Stage 1: markdown — 含占位符正文；无结构时用提取纯文本
            if use_llm and content_list:
                markdown_text = parsing_service.content_list_to_markdown(
                    content_list,
                    table_ids=table_ids_by_block,
                    image_ids=image_ids_by_block,
                )
            elif use_llm and not markdown_text:
                markdown_text = plain_text
            if use_llm and markdown_text:
                md_path = Path(settings.CHUNKS_DIR) / f"{doc_id}.md"
                md_path.write_text(markdown_text, encoding="utf-8")
            await asyncio.sleep(random.uniform(0.1, 0.3))
            if not await _advance_stage(db, task_id, 1):
                if _is_cancelled(task_id):
                    await _finalize_cancel(db, doc_id, task_id, owner_id=owner_id, filename=original_name)
                return

            # Stage 2: chunk — 结构化分块（带 page_idx + media_refs）
            chunks: list[dict] = []
            if use_llm:
                if content_list:
                    chunks = parsing_service.content_list_to_chunks(
                        content_list,
                        split_by=settings.MINERU_SPLIT_BY,
                        chunk_size=settings.MINERU_CHUNK_MAX_CHARS,
                        overlap=settings.MINERU_CHUNK_OVERLAP,
                        table_ids=table_ids_by_block,
                        image_ids=image_ids_by_block,
                    )
                else:
                    chunks = parsing_service.plain_text_to_chunks(
                        plain_text,
                        chunk_size=settings.MINERU_CHUNK_MAX_CHARS,
                        overlap=settings.MINERU_CHUNK_OVERLAP,
                    )
                _chunks_path(doc_id).parent.mkdir(parents=True, exist_ok=True)
                _chunks_path(doc_id).write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
            else:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                # mock 环境也写出分块，保证 hybrid 检索有可召回的文档片段
                mock_text = (
                    f"文档《{original_name}》的摘要内容。"
                    "候选人掌握 Python、LangChain、FastAPI、Docker 等技能，"
                    "曾就职于某科技有限公司担任后端工程师，毕业于清华大学计算机科学专业。"
                    "主导开发 GraphRAG知识库系统。"
                )
                chunks = [
                    {"text": mock_text, "page_idx": 0, "chunk_index": 0, "media_refs": []},
                    {"text": f"{original_name} 补充说明：具备 3 年以上后端开发经验。", "page_idx": 1, "chunk_index": 1, "media_refs": []},
                ]
                _chunks_path(doc_id).parent.mkdir(parents=True, exist_ok=True)
                _chunks_path(doc_id).write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
            if not await _advance_stage(db, task_id, 2):
                if _is_cancelled(task_id):
                    await _finalize_cancel(db, doc_id, task_id, owner_id=owner_id, filename=original_name)
                return

            # Stage 3: kg — 文本抽取 + TABLE/IMAGE 节点
            if use_llm and chunks and deepseek_key:
                kg = await kg_extraction.extract_kg(doc_id, chunks, deepseek_key)
            elif use_llm:
                kg = {"doc_id": doc_id, "nodes": [], "edges": [], "meta": {"total_nodes": 0, "total_edges": 0, "created_at": datetime.utcnow().isoformat() + "Z"}}
            else:
                await asyncio.sleep(random.uniform(0.5, 1.2))
                kg = _mock_kg(doc_id, original_name)

            # 类型独占权：丢弃文本抽取伪造的 TABLE/IMAGE（SPEC §9.4）
            kg = table_service.filter_reserved_kg_types(kg)

            if use_llm:
                if table_records:
                    kg = table_service.attach_to_kg(kg, table_records, doc_id, original_name=original_name)
                if image_metas:
                    kg = image_service.attach_to_kg(kg, image_metas, doc_id, original_name=original_name)
                    media_store.write_manifest(
                        doc_id,
                        [r["table_id"] for r in table_records],
                        [m["image_id"] for m in image_metas if m.get("image_id")],
                    )
                if not any(n.get("type") == "DOCUMENT" for n in kg.get("nodes") or []):
                    if table_records or image_metas or content_list:
                        kg = media_store.ensure_document_node(kg, doc_id, original_name)

            _kg_path(doc_id).write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")
            if not await _advance_stage(db, task_id, 3):
                if _is_cancelled(task_id):
                    await _finalize_cancel(db, doc_id, task_id, owner_id=owner_id, filename=original_name)
                return

            # Stage 4: vector — SPEC-VECTOR: embed chunks and persist to Milvus
            try:
                embedding_key = await key_vault_service.get_verified_secret_or_none(db, owner_id, "embedding")
                if chunks and embedding_key and not settings.MOCK_EXTERNAL_SERVICES:
                    texts = [(c.get("text") or "")[:3900] for c in chunks]
                    vectors = await embedding_service.embed_texts(embedding_key, texts)
                    count = vector_store.upsert_chunks(
                        owner_id=owner_id,
                        doc_id=doc_id,
                        chunks=chunks,
                        vectors=vectors,
                    )
                    logger.info("indexed %s vectors for doc %s", count, doc_id)
                else:
                    logger.info("skip vector stage for %s (mock or missing embedding key/chunks)", doc_id)
            except Exception as vec_exc:
                # non-fatal: keyword retrieval still works from chunks file
                logger.warning("vector stage failed for %s: %s", doc_id, vec_exc)
            if not await _advance_stage(db, task_id, 4):
                if _is_cancelled(task_id):
                    await _finalize_cancel(db, doc_id, task_id, owner_id=owner_id, filename=original_name)
                return
        except Exception as e:
            await _fail_task(db, doc_id, task_id, f"索引处理失败: {e}", owner_id=owner_id, filename=original_name)
            return

        # 更新 Document
        result2 = await db.execute(select(Document).where(Document.doc_id == doc_id))
        doc = result2.scalar_one_or_none()
        node_count = 0
        if doc:
            doc.status = "indexed"
            doc.node_count = len(kg["nodes"])
            doc.edge_count = len(kg["edges"])
            node_count = doc.node_count
            if page_count:
                doc.page_count = page_count
            await db.commit()
        # 更新 Task
        result3 = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
        task = result3.scalar_one_or_none()
        if task:
            task.status = "indexed"
            task.progress = 100
            await db.commit()
        await _notify_index_result(
            db,
            owner_id,
            doc_id=doc_id,
            task_id=task_id,
            filename=original_name,
            success=True,
            node_count=node_count,
        )

async def get_task(db: AsyncSession, task_id: str) -> IndexTask:
    result = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise ValueError("4042:任务不存在")
    return task
