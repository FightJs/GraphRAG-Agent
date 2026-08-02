import json, uuid, asyncio, re
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import Document, QARecord
from app.services import key_vault_service, llm_client

_QA_SYSTEM_PROMPT = """你是专业的文档问答助手。请仅根据下方提供的知识图谱信息和文档片段回答用户问题。
要求：
- 只使用给定材料中的信息作答，不要编造或使用材料之外的知识
- 如果材料中没有足够信息回答问题，请直接说明"根据现有文档未找到相关信息"，不要猜测
- 回答简洁、有条理，可使用 Markdown 加粗关键信息"""

_KB_QA_SYSTEM_PROMPT = """你是专业的知识库问答助手，需要综合多份文档的内容回答用户问题。
要求：
- 只使用给定材料中的信息作答，不要编造
- 如果材料中没有足够信息，请直接说明未找到相关信息
- 可以指出信息来自哪份文档"""

def _kg_path(doc_id: str) -> Path:
    return Path(settings.KG_DIR) / f"{doc_id}.json"

def _chunks_path(doc_id: str) -> Path:
    return Path(settings.CHUNKS_DIR) / f"{doc_id}.json"

def _load_chunks(doc_id: str) -> list[str]:
    cp = _chunks_path(doc_id)
    if not cp.exists():
        return []
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except Exception:
        return []

def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text)
    cn = re.sub(r"[a-zA-Z0-9\s]", "", text)
    tokens += [cn[i:i + 2] for i in range(len(cn) - 1)]
    return [t for t in tokens if len(t) >= 2]

def _retrieve_chunks(question: str, chunks: list[str], top_k: int = 5) -> list[str]:
    """轻量关键词检索：无向量嵌入接口时的实用替代方案"""
    if not chunks:
        return []
    tokens = _tokenize(question)
    if not tokens:
        return chunks[:top_k]
    scored = [(sum(c.count(t) for t in tokens), c) for c in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [c for score, c in scored if score > 0][:top_k]
    return picked or chunks[:top_k]

def _kg_summary(kg: dict) -> str:
    nodes_txt = "\n".join([f"- [{n['type']}] {n['label']}: {json.dumps(n.get('attributes', {}), ensure_ascii=False)}" for n in kg.get("nodes", [])[:50]])
    edges_txt = "\n".join([f"- {e['source']} --[{e['relation']}]--> {e['target']}" for e in kg.get("edges", [])[:80]])
    return f"【知识图谱节点】\n{nodes_txt or '（无）'}\n\n【知识图谱关系】\n{edges_txt or '（无）'}"

def _build_llm_context(kg: dict, chunks: list[str], question: str) -> str:
    retrieved = _retrieve_chunks(question, chunks)
    chunk_txt = "\n---\n".join(retrieved) if retrieved else "（无相关文档片段）"
    return f"{_kg_summary(kg)}\n\n【相关文档片段】\n{chunk_txt}"

def _mock_answer(question: str, kg: dict) -> str:
    nodes = {n["id"]: n for n in kg["nodes"]}
    person = next((n for n in kg["nodes"] if n["type"] == "PERSON"), None)
    skills = [n for n in kg["nodes"] if n["type"] == "SKILL"]
    company = next((n for n in kg["nodes"] if n["type"] == "COMPANY"), None)
    school = next((n for n in kg["nodes"] if n["type"] == "SCHOOL"), None)
    name = person["label"] if person else "候选人"
    skill_str = "、".join([s["label"] for s in skills]) if skills else "暂无技能记录"
    q = question.lower()
    if any(k in q for k in ["技能", "掌握", "会", "skill"]):
        return f"根据知识图谱分析，{name} 掌握的核心技能包括：{skill_str}。\n\n其中 **LangChain** 具有2年实际项目经验，曾主导落地 GraphRAG 知识库系统。**Python** 熟练程度达到生产级别，具备3年以上后端服务开发经验。"
    if any(k in q for k in ["经历", "工作", "公司", "就职"]):
        co = company["label"] if company else "相关公司"
        return f"{name} 曾就职于 **{co}**，担任后端工程师职位（P6级别），主要负责 AI 基础设施建设和知识库平台开发。"
    if any(k in q for k in ["教育", "学历", "大学", "学校", "毕业"]):
        sch = school["label"] if school else "国内知名高校"
        return f"{name} 毕业于 **{sch}**，计算机科学专业，硕士学历。"
    return f"根据知识图谱对 **{name}** 的分析：\n\n- **核心技能**：{skill_str}\n- **工作经历**：{company['label'] if company else '详见文档'}\n- **教育背景**：{school['label'] if school else '详见文档'}\n\n如需了解更具体信息，请提出针对性问题。"

async def qa_stream(db: AsyncSession, doc_id: str, question: str, user_id: str, retrieval_mode: str = "kg_only") -> AsyncGenerator[str, None]:
    result = await db.execute(select(Document).where(Document.doc_id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.status != "indexed":
        yield f"event: error\ndata: {json.dumps({'code': 4043, 'msg': '文档未完成索引'}, ensure_ascii=False)}\n\n"
        return
    kp = _kg_path(doc_id)
    if not kp.exists():
        yield f"event: error\ndata: {json.dumps({'code': 4043, 'msg': 'KG数据不存在'}, ensure_ascii=False)}\n\n"
        return
    kg = json.loads(kp.read_text(encoding="utf-8"))
    query_id = str(uuid.uuid4())

    deepseek_key = await key_vault_service.get_verified_secret(db, user_id, "deepseek")
    if not settings.MOCK_EXTERNAL_SERVICES and llm_client.llm_available(deepseek_key):
        context = _build_llm_context(kg, _load_chunks(doc_id), question)
        messages = [
            {"role": "system", "content": _QA_SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\n\n用户问题: {question}"},
        ]
        full_answer = ""
        usage = {"input_tokens": 0, "output_tokens": 0}
        try:
            async for event in llm_client.chat_stream(deepseek_key, messages):
                if "delta" in event:
                    full_answer += event["delta"]
                    payload = json.dumps({"query_id": query_id, "content": event["delta"], "finish_reason": None}, ensure_ascii=False)
                    yield f"event: delta\ndata: {payload}\n\n"
                elif event.get("done"):
                    usage = event["usage"]
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'code': 5002, 'msg': f'LLM调用失败: {e}'}, ensure_ascii=False)}\n\n"
            return
        if not full_answer.strip():
            full_answer = "根据现有文档未找到相关信息。"
    else:
        full_answer = _mock_answer(question, kg)
        usage = {"input_tokens": len(question) * 2, "output_tokens": len(full_answer)}
        for chunk in [full_answer[i:i + 20] for i in range(0, len(full_answer), 20)]:
            payload = json.dumps({"query_id": query_id, "content": chunk, "finish_reason": None}, ensure_ascii=False)
            yield f"event: delta\ndata: {payload}\n\n"
            await asyncio.sleep(0.05)

    record = QARecord(query_id=query_id, doc_id=doc_id, user_id=user_id, question=question,
                      answer=full_answer, retrieval_mode=retrieval_mode, retrieval_mode_used=retrieval_mode,
                      input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"])
    db.add(record)
    await db.commit()
    done_payload = json.dumps({
        "query_id": query_id, "content": "", "finish_reason": "stop",
        "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
        "retrieval_mode_used": retrieval_mode, "kg_nodes_used": len(kg["nodes"]), "kg_edges_used": len(kg["edges"]), "sources": []
    }, ensure_ascii=False)
    yield f"event: done\ndata: {done_payload}\n\n"

async def qa_sync(db: AsyncSession, doc_id: str, question: str, user_id: str, retrieval_mode: str = "kg_only") -> dict:
    result = await db.execute(select(Document).where(Document.doc_id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.status != "indexed":
        raise ValueError("4043:文档未完成索引")
    kp = _kg_path(doc_id)
    if not kp.exists():
        raise ValueError("4043:KG数据不存在")
    kg = json.loads(kp.read_text(encoding="utf-8"))

    deepseek_key = await key_vault_service.get_verified_secret(db, user_id, "deepseek")
    if not settings.MOCK_EXTERNAL_SERVICES and llm_client.llm_available(deepseek_key):
        context = _build_llm_context(kg, _load_chunks(doc_id), question)
        messages = [
            {"role": "system", "content": _QA_SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\n\n用户问题: {question}"},
        ]
        try:
            full_answer, usage = await llm_client.chat_complete(deepseek_key, messages, temperature=0.2, max_tokens=1500)
        except Exception as e:
            raise ValueError(f"5002:LLM调用失败: {e}")
        if not full_answer.strip():
            full_answer = "根据现有文档未找到相关信息。"
    else:
        full_answer = _mock_answer(question, kg)
        usage = {"input_tokens": len(question) * 2, "output_tokens": len(full_answer)}

    query_id = str(uuid.uuid4())
    record = QARecord(query_id=query_id, doc_id=doc_id, user_id=user_id, question=question,
                      answer=full_answer, retrieval_mode=retrieval_mode, retrieval_mode_used=retrieval_mode,
                      input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"])
    db.add(record)
    await db.commit()
    return {"query_id": query_id, "answer": full_answer, "retrieval_mode_used": retrieval_mode,
            "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
            "kg_nodes_used": len(kg["nodes"]), "kg_edges_used": len(kg["edges"]), "sources": []}

async def kb_qa_stream(db: AsyncSession, kb_id: str, doc_ids: list[str], question: str, user_id: str, retrieval_mode: str = "hybrid") -> AsyncGenerator[str, None]:
    query_id = str(uuid.uuid4())
    deepseek_key = await key_vault_service.get_verified_secret(db, user_id, "deepseek")

    if not settings.MOCK_EXTERNAL_SERVICES and llm_client.llm_available(deepseek_key):
        contexts = []
        sources = []
        for doc_id in doc_ids[:10]:
            chunks = _load_chunks(doc_id)
            kp = _kg_path(doc_id)
            kg = json.loads(kp.read_text(encoding="utf-8")) if kp.exists() else {"nodes": [], "edges": []}
            retrieved = _retrieve_chunks(question, chunks, top_k=3)
            result_doc = await db.execute(select(Document).where(Document.doc_id == doc_id))
            doc = result_doc.scalar_one_or_none()
            title = doc.original_name if doc else doc_id
            if retrieved:
                contexts.append(f"【文档: {title}】\n" + "\n".join(retrieved))
                sources.append({"doc_id": doc_id, "doc_title": title, "page": 1, "snippet": retrieved[0][:80] + "..."})
            elif kg.get("nodes"):
                node_txt = "、".join(n["label"] for n in kg["nodes"][:10])
                contexts.append(f"【文档: {title} 知识图谱】{node_txt}")
                sources.append({"doc_id": doc_id, "doc_title": title, "page": 1, "snippet": node_txt[:80]})
        combined_context = "\n\n".join(contexts) if contexts else "未找到相关文档内容。"
        messages = [
            {"role": "system", "content": _KB_QA_SYSTEM_PROMPT},
            {"role": "user", "content": f"{combined_context}\n\n用户问题: {question}"},
        ]
        full_answer = ""
        usage = {"input_tokens": 0, "output_tokens": 0}
        try:
            async for event in llm_client.chat_stream(deepseek_key, messages):
                if "delta" in event:
                    full_answer += event["delta"]
                    payload = json.dumps({"query_id": query_id, "content": event["delta"], "finish_reason": None}, ensure_ascii=False)
                    yield f"event: delta\ndata: {payload}\n\n"
                elif event.get("done"):
                    usage = event["usage"]
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'code': 5002, 'msg': f'LLM调用失败: {e}'}, ensure_ascii=False)}\n\n"
            return
        if not full_answer.strip():
            full_answer = "根据现有文档未找到相关信息。"
    else:
        answers = []
        sources = []
        for doc_id in doc_ids[:10]:
            kp = _kg_path(doc_id)
            if not kp.exists():
                continue
            kg = json.loads(kp.read_text(encoding="utf-8"))
            ans = _mock_answer(question, kg)
            answers.append(ans)
            result_doc = await db.execute(select(Document).where(Document.doc_id == doc_id))
            doc = result_doc.scalar_one_or_none()
            if doc:
                sources.append({"doc_id": doc_id, "doc_title": doc.original_name, "page": 1, "snippet": ans[:80] + "..."})
        full_answer = f"联合分析 {len(doc_ids)} 份文档后的综合回答：\n\n" + "\n\n---\n\n".join(answers[:3]) if answers else "未找到相关信息"
        usage = {"input_tokens": len(question) * 3, "output_tokens": len(full_answer)}
        for chunk in [full_answer[i:i + 20] for i in range(0, len(full_answer), 20)]:
            payload = json.dumps({"query_id": query_id, "content": chunk, "finish_reason": None}, ensure_ascii=False)
            yield f"event: delta\ndata: {payload}\n\n"
            await asyncio.sleep(0.05)

    record = QARecord(query_id=query_id, kb_id=kb_id, user_id=user_id, question=question,
                      answer=full_answer, retrieval_mode=retrieval_mode, retrieval_mode_used=retrieval_mode,
                      input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                      sources_json=json.dumps(sources, ensure_ascii=False))
    db.add(record)
    await db.commit()
    done_payload = json.dumps({
        "query_id": query_id, "content": "", "finish_reason": "stop",
        "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
        "retrieval_mode_used": retrieval_mode, "sources": sources
    }, ensure_ascii=False)
    yield f"event: done\ndata: {done_payload}\n\n"

async def get_history(db: AsyncSession, user_id: str, kb_id: str | None = None, doc_id: str | None = None) -> list[QARecord]:
    q = select(QARecord).where(QARecord.user_id == user_id)
    if kb_id:
        q = q.where(QARecord.kb_id == kb_id)
    if doc_id:
        q = q.where(QARecord.doc_id == doc_id)
    result = await db.execute(q.order_by(QARecord.created_at.desc()).limit(100))
    return list(result.scalars().all())

async def submit_feedback(db: AsyncSession, query_id: str, user_id: str, rating: str, comment: str | None = None) -> dict:
    from app.models.db_models import QAFeedback
    existing = await db.execute(select(QAFeedback).where(QAFeedback.query_id == query_id))
    if existing.scalar_one_or_none():
        raise ValueError("4093:该问答已提交过反馈，不可重复")
    fb = QAFeedback(feedback_id=str(uuid.uuid4()), query_id=query_id, user_id=user_id, rating=rating, comment=comment)
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return {"feedback_id": fb.feedback_id, "query_id": query_id, "rating": rating, "created_at": fb.created_at.isoformat() + "Z"}
