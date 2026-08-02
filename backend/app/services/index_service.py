import asyncio, json, uuid, random
from datetime import datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import Document, IndexTask
from app.services import parsing_service, kg_extraction, llm_client

STAGES = [
    {"name": "parse",    "label": "文档解析"},
    {"name": "markdown", "label": "Markdown转换"},
    {"name": "chunk",    "label": "文本分块"},
    {"name": "kg",       "label": "KG实体抽取"},
    {"name": "vector",   "label": "向量化索引"},
]

def _chunks_path(doc_id: str) -> Path:
    return Path(settings.CHUNKS_DIR) / f"{doc_id}.json"

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
    asyncio.create_task(_run_pipeline(doc_id, task.task_id, doc.original_name, doc.file_path, doc.file_format))
    return task

async def _advance_stage(db: AsyncSession, task_id: str, index: int) -> bool:
    result = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        return False
    stages = json.loads(task.stages_json)
    stages[index]["status"] = "done"
    stages[index]["progress"] = 100
    task.stages_json = json.dumps(stages, ensure_ascii=False)
    task.progress = int((index + 1) / len(STAGES) * 100)
    await db.commit()
    return True

async def _fail_task(db: AsyncSession, doc_id: str, task_id: str, message: str):
    result = await db.execute(select(Document).where(Document.doc_id == doc_id))
    doc = result.scalar_one_or_none()
    if doc:
        doc.status = "failed"
        doc.error_message = message
        await db.commit()
    result2 = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
    task = result2.scalar_one_or_none()
    if task:
        task.status = "failed"
        task.error_message = message
        await db.commit()

async def _run_pipeline(doc_id: str, task_id: str, original_name: str, file_path: str, file_format: str):
    """5阶段索引 Pipeline（后台运行）。配置了 DEEPSEEK_API_KEY 时走真实解析+LLM抽取，否则走 mock。"""
    from app.database import AsyncSessionLocal
    use_llm = llm_client.llm_available()

    async with AsyncSessionLocal() as db:
        try:
            # Stage 0: parse — 提取原始文本
            if use_llm:
                text, page_count = parsing_service.extract_text(file_path, file_format)
            else:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                text, page_count = "", 0
            if not await _advance_stage(db, task_id, 0):
                return

            # Stage 1: markdown — 本项目直接使用提取的纯文本作为 markdown 表示
            await asyncio.sleep(random.uniform(0.2, 0.5))
            if not await _advance_stage(db, task_id, 1):
                return

            # Stage 2: chunk — 文本分块
            chunks: list[str] = []
            if use_llm:
                chunks = parsing_service.chunk_text(text)
                _chunks_path(doc_id).write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
            else:
                await asyncio.sleep(random.uniform(0.3, 0.8))
            if not await _advance_stage(db, task_id, 2):
                return

            # Stage 3: kg — 知识图谱抽取
            if use_llm and chunks:
                kg = await kg_extraction.extract_kg(doc_id, chunks)
            elif use_llm:
                kg = {"doc_id": doc_id, "nodes": [], "edges": [], "meta": {"total_nodes": 0, "total_edges": 0, "created_at": datetime.utcnow().isoformat() + "Z"}}
            else:
                await asyncio.sleep(random.uniform(0.5, 1.2))
                kg = _mock_kg(doc_id, original_name)
            _kg_path(doc_id).write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")
            if not await _advance_stage(db, task_id, 3):
                return

            # Stage 4: vector — 关键词索引就地生效于 chunks 文件，此处仅推进进度
            await asyncio.sleep(random.uniform(0.3, 0.7))
            if not await _advance_stage(db, task_id, 4):
                return
        except Exception as e:
            await _fail_task(db, doc_id, task_id, f"索引处理失败: {e}")
            return

        # 更新 Document
        result2 = await db.execute(select(Document).where(Document.doc_id == doc_id))
        doc = result2.scalar_one_or_none()
        if doc:
            doc.status = "indexed"
            doc.node_count = len(kg["nodes"])
            doc.edge_count = len(kg["edges"])
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

async def get_task(db: AsyncSession, task_id: str) -> IndexTask:
    result = await db.execute(select(IndexTask).where(IndexTask.task_id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise ValueError("4042:任务不存在")
    return task
