import json, uuid, asyncio, re, logging
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import Document, QARecord
from app.services import key_vault_service, llm_client, embedding_service, vector_store, media_store
from app.services.parsing_service import normalize_chunks

logger = logging.getLogger(__name__)

_QA_SYSTEM_PROMPT_KG_ONLY = """你是专业的文档问答助手。下方仅提供知识图谱（节点与关系），没有原文段落。
要求：
- 只根据知识图谱中的实体、关系和属性作答，不要编造或使用材料之外的知识
- 优先串联相关关系（谁与谁如何关联），必要时概括图谱结构
- 如果图谱中没有足够信息回答问题，请直接说明"根据现有知识图谱未找到相关信息"，不要猜测
- 回答简洁、有条理，可使用 Markdown 加粗关键信息"""

_KB_QA_SYSTEM_PROMPT = """你是专业的知识库问答助手，需要综合多份文档的内容回答用户问题。
要求：
- 只使用给定材料中的信息作答，不要编造
- 如果材料中没有足够信息，请直接说明未找到相关信息
- 可以指出信息来自哪份文档"""

_VALID_MODES = {"kg_only", "agentic", "auto"}
_AGENTIC_PROMPT = """你是专业的文档问答助手，采用子查询分解 + 三路召回（向量 / 关键词 / 知识图谱）的 RRF 融合结果作答。
要求：
- 综合知识图谱结构与多路检索片段作答，精确细节以片段为准
- 只使用给定材料中的信息，不要编造
- 如果材料中没有足够信息回答问题，请直接说明"根据现有文档未找到相关信息"，不要猜测
- 回答简洁、有条理，可使用 Markdown 加粗关键信息"""
_AUTO_AGENTIC_NODE_THRESHOLD = 200

def _kg_path(doc_id: str) -> Path:
    return Path(settings.KG_DIR) / f"{doc_id}.json"

def _chunks_path(doc_id: str) -> Path:
    return Path(settings.CHUNKS_DIR) / f"{doc_id}.json"

def _load_chunks(doc_id: str) -> list[dict]:
    cp = _chunks_path(doc_id)
    if not cp.exists():
        return []
    try:
        return normalize_chunks(json.loads(cp.read_text(encoding="utf-8")))
    except Exception:
        return []

def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text)
    cn = re.sub(r"[a-zA-Z0-9\s]", "", text)
    tokens += [cn[i:i + 2] for i in range(len(cn) - 1)]
    return [t for t in tokens if len(t) >= 2]

def _normalize_mode(mode: str | None, kg: dict | None = None) -> str:
    m = (mode or "kg_only").strip().lower()
    # 旧别名统一映射到 RRF Agentic
    if m in {"hybrid", "semantic"}:
        m = "agentic"
    if m == "auto":
        node_count = len((kg or {}).get("nodes") or [])
        return "agentic" if node_count > _AUTO_AGENTIC_NODE_THRESHOLD else "kg_only"
    return m if m in {"kg_only", "agentic"} else "kg_only"

def _retrieve_chunks(question: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """轻量关键词检索：无向量嵌入接口时的实用替代方案"""
    if not chunks:
        return []
    tokens = _tokenize(question)
    if not tokens:
        return chunks[:top_k]
    scored = [(sum(c["text"].count(t) for t in tokens), c) for c in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [c for score, c in scored if score > 0][:top_k]
    return picked or chunks[:top_k]

def _page_number(chunk: dict) -> int:
    page_idx = chunk.get("page_idx")
    if page_idx is None:
        return 1
    try:
        return int(page_idx) + 1
    except (TypeError, ValueError):
        return 1

def _chunk_to_source(chunk: dict, doc_id: str, doc_title: str, max_len: int = 120) -> dict:
    text = (chunk.get("text") or "").strip()
    excerpt = text[:max_len] + ("..." if len(text) > max_len else "")
    return {
        "doc_id": doc_id,
        "doc_name": doc_title,
        "doc_title": doc_title,
        "page": _page_number(chunk),
        "excerpt": excerpt,
        "snippet": excerpt,
    }

def _label_hit(label: str, question: str) -> bool:
    label = (label or "").strip()
    if not label or len(label) < 2:
        return False
    if label in question:
        return True
    grams = [label[i:i + 2] for i in range(len(label) - 1)]
    if not grams:
        return False
    hits = sum(1 for g in grams if g in question)
    return hits / len(grams) >= 0.5

def _node_text_blob(node: dict) -> str:
    attrs = node.get("attributes") or {}
    try:
        attrs_txt = json.dumps(attrs, ensure_ascii=False)
    except Exception:
        attrs_txt = str(attrs)
    return f"{node.get('label', '')} {attrs_txt}"

def _select_kg_for_question(kg: dict, question: str, max_nodes: int = 50, max_edges: int = 80) -> dict:
    """按问题抽子图（实体命中 + 最多两跳邻居）；无命中时退回截断全图。"""
    nodes = kg.get("nodes") or []
    edges = kg.get("edges") or []
    if not nodes:
        return {"nodes": [], "edges": []}

    question = question or ""
    seed_ids = {
        n["id"] for n in nodes
        if _label_hit(str(n.get("label", "")), question) or _label_hit(_node_text_blob(n), question)
    }
    # 宽松兜底：问题词出现在 label/attributes 任一处也算命中（避免无意义地倒全图）
    if not seed_ids:
        q_tokens = [t for t in _tokenize(question) if len(t) >= 2]
        for n in nodes:
            blob = _node_text_blob(n)
            if any(t in blob for t in q_tokens):
                seed_ids.add(n["id"])
    if not seed_ids:
        # KG-Only 语义：未命中实体时不回退全图，避免把无关原文/全图交给 LLM
        return {"nodes": [], "edges": []}

    # 1-hop then 2-hop expansion, preserving seed priority in output
    adj: dict[str, set[str]] = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s is None or t is None:
            continue
        adj.setdefault(str(s), set()).add(str(t))
        adj.setdefault(str(t), set()).add(str(s))

    hop1 = set(seed_ids)
    for sid in seed_ids:
        hop1 |= {n for n in adj.get(str(sid), set())}
    hop2 = set(hop1)
    for nid in hop1:
        hop2 |= {n for n in adj.get(str(nid), set())}

    id_order = {nid: (0 if nid in seed_ids else 1 if nid in hop1 else 2) for nid in hop2}
    ordered_ids = sorted(id_order, key=lambda nid: (id_order[nid], str(nid)))
    keep_ids = set(ordered_ids[:max_nodes])

    selected_nodes = [n for n in nodes if n["id"] in keep_ids]
    selected_edges = [e for e in edges if e.get("source") in keep_ids and e.get("target") in keep_ids]
    if not selected_nodes:
        return {"nodes": nodes[:max_nodes], "edges": edges[:max_edges]}
    return {"nodes": selected_nodes[:max_nodes], "edges": selected_edges[:max_edges]}

def _node_label_map(kg: dict) -> dict[str, str]:
    return {str(n.get("id")): str(n.get("label", n.get("id", ""))) for n in kg.get("nodes") or []}

def _kg_summary(kg: dict) -> str:
    labels = _node_label_map(kg)
    nodes_txt = "\n".join(
        f"- [{n.get('type', 'OTHER')}] {n.get('label', '')}: {json.dumps(n.get('attributes', {}), ensure_ascii=False)}"
        for n in kg.get("nodes", [])[:50]
    )
    edges_txt = "\n".join(
        f"- {labels.get(str(e.get('source')), e.get('source'))} --[{e.get('relation', '')}]--> {labels.get(str(e.get('target')), e.get('target'))}"
        for e in kg.get("edges", [])[:80]
    )
    return f"【知识图谱节点】\n{nodes_txt or '（无）'}\n\n【知识图谱关系】\n{edges_txt or '（无）'}"

def _build_retrieval_context(
    kg: dict,
    chunks: list[dict],
    question: str,
    retrieval_mode: str,
    doc_id: str = "",
    doc_title: str = "",
) -> tuple[str, list[dict], str]:
    """按模式构建 LLM 上下文。返回 (context, sources, mode_used)。"""
    mode = _normalize_mode(retrieval_mode, kg)

    if mode == "kg_only":
        subgraph = _select_kg_for_question(kg, question)
        context = (
            "当前为 KG-Only 检索模式：仅使用知识图谱。\n\n"
            f"{_kg_summary(subgraph)}"
        )
        return context, [], mode

    retrieved = _retrieve_chunks(question, chunks, top_k=5)
    sources = [_chunk_to_source(c, doc_id, doc_title) for c in retrieved] if doc_title else []
    # 非 KG-Only：子图 + 原文片段（KB 多文档路径）
    subgraph = _select_kg_for_question(kg, question)
    chunk_txt = "\n---\n".join(media_store.expand_placeholders(doc_id, c["text"]) for c in retrieved) if retrieved else "（无相关文档片段）"
    context = (
        "当前为 RRF Agentic 检索模式：知识图谱 + 相关文档片段。\n\n"
        f"{_kg_summary(subgraph)}\n\n【相关文档片段】\n{chunk_txt}"
    )
    return context, sources, mode

def _system_prompt_for_mode(mode: str) -> str:
    return _QA_SYSTEM_PROMPT_KG_ONLY if mode == "kg_only" else _AGENTIC_PROMPT

def _hit_to_source(hit: dict, doc_id: str, doc_title: str) -> dict:
    text = (hit.get("text") or "").strip()
    excerpt = text[:120] + ("..." if len(text) > 120 else "")
    return {
        "doc_id": hit.get("doc_id") or doc_id,
        "doc_name": doc_title,
        "doc_title": doc_title,
        "page": int(hit.get("page_idx") or 0) + 1,
        "excerpt": excerpt,
        "snippet": excerpt,
        "chunk_id": hit.get("chunk_id"),
        "score": hit.get("score"),
    }

def _rrf_fuse(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion over ranked hit lists keyed by chunk_id."""
    scores: dict[str, float] = {}
    keep: dict[str, dict] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            key = str(hit.get("chunk_id") or hit.get("text", "")[:64])
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in keep:
                item = dict(hit)
                item["_rrf_sources"] = {hit.get("source") or "unknown"}
                keep[key] = item
            else:
                keep[key]["_rrf_sources"].add(hit.get("source") or "unknown")
    fused = []
    for key, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        item = keep[key]
        item["score"] = score
        item["source"] = "rrf:" + "+".join(sorted(item.get("_rrf_sources") or []))
        fused.append(item)
    return fused

def _decompose_queries(question: str, max_queries: int = 3) -> list[str]:
    """Heuristic sub-query decomposition for agentic retrieval (no LLM required)."""
    q = (question or "").strip()
    if not q:
        return []
    parts = [p.strip() for p in re.split(r"[？?。！!；;，,、\n]+", q) if p.strip()]
    queries = [q]
    for p in parts:
        if p and p not in queries:
            queries.append(p)
    tokens = _tokenize(q)
    if tokens:
        key_phrase = " ".join(tokens[:6])
        if key_phrase not in queries:
            queries.append(key_phrase)
    return queries[:max_queries]

async def _agentic_retrieve(
    user_id: str,
    question: str,
    doc_id: str,
    doc_title: str,
    kg: dict,
    top_k: int = 5,
    db: AsyncSession | None = None,
) -> tuple[str, list[dict], list[str]]:
    """RRF Agentic: decompose question → three-way retrieve (vector/keyword/KG) → RRF fuse."""
    sub_queries = _decompose_queries(question)
    subgraph = _select_kg_for_question(kg, question)
    embedding_key = await key_vault_service.get_verified_secret_or_none(db, user_id, "embedding") if db else None
    chunks = _load_chunks(doc_id)
    ranked_lists: list[list[dict]] = []
    for sq in sub_queries:
        vector_hits: list[dict] = []
        if embedding_key and not settings.MOCK_EXTERNAL_SERVICES:
            try:
                qvec = await embedding_service.embed_query(embedding_key, sq)
                raw = vector_store.search(query_vector=qvec, owner_id=user_id, doc_ids=[doc_id], top_k=top_k)
                for i, h in enumerate(raw, start=1):
                    item = dict(h)
                    item["source"] = "vector"
                    item["_rank"] = i
                    vector_hits.append(item)
            except Exception as exc:
                logger.warning("agentic vector search failed for %r: %s", sq, exc)
        keyword_hits: list[dict] = []
        retrieved = _retrieve_chunks(sq, chunks, top_k=top_k)
        for i, c in enumerate(retrieved, start=1):
            keyword_hits.append({
                "doc_id": doc_id,
                "chunk_id": c.get("chunk_index"),
                "text": c.get("text") or "",
                "page_idx": c.get("page_idx") or 0,
                "media_refs": c.get("media_refs") or [],
                "score": float(max(0, sum(c.get("text", "").count(t) for t in _tokenize(sq)))),
                "source": "keyword",
                "_rank": i,
            })
        ranked_lists.extend(hits for hits in (vector_hits, keyword_hits) if hits)
    fused = _rrf_fuse(ranked_lists, k=60) if ranked_lists else []
    fused = fused[:top_k]
    sources = [_hit_to_source(h, doc_id, doc_title) for h in fused]
    chunk_txt = "\n---\n".join(media_store.expand_placeholders(doc_id, h["text"]) for h in fused) if fused else "（无相关文档片段）"
    subq_txt = "\n".join(f"- {sq}" for sq in sub_queries) if sub_queries else "- （无）"
    context = (
        "当前为 RRF Agentic 检索模式：子查询分解 + 三路召回（向量 / 关键词 / 知识图谱）。\n\n"
        f"【子查询】\n{subq_txt}\n\n"
        f"{_kg_summary(subgraph)}\n\n【融合检索文档片段】\n{chunk_txt}"
    )
    return context, sources, sub_queries

def _mock_answer(question: str, kg: dict) -> str:
    if not kg.get("nodes"):
        return "根据现有知识图谱未找到相关信息。"
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
    mode_used = _normalize_mode(retrieval_mode, kg)
    doc_title = doc.original_name or doc_id
    if mode_used == "agentic":
        context, sources, _ = await _agentic_retrieve(user_id, question, doc_id, doc_title, kg, db=db)
    else:
        context, sources, mode_used = _build_retrieval_context(
            kg, _load_chunks(doc_id), question, mode_used, doc_id=doc_id, doc_title=doc_title
        )

    deepseek_key = await key_vault_service.get_verified_secret(db, user_id, "deepseek")
    if not settings.MOCK_EXTERNAL_SERVICES and llm_client.llm_available(deepseek_key):
        messages = [
            {"role": "system", "content": _system_prompt_for_mode(mode_used)},
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
            full_answer = "根据现有文档未找到相关信息。" if mode_used == "agentic" else "根据现有知识图谱未找到相关信息。"
    else:
        # KG-Only：只把命中的两跳子图交给 mock/LLM，不注入原文
        subgraph_for_ans = _select_kg_for_question(kg, question) if mode_used == "kg_only" else kg
        full_answer = _mock_answer(question, subgraph_for_ans)
        if mode_used == "agentic" and sources:
            full_answer += "\n\n**混合检索补充（原文片段）**\n" + "\n".join(
                f"- {s['excerpt']}" for s in sources[:2]
            )
        usage = {"input_tokens": len(question) * 2, "output_tokens": len(full_answer)}
        for chunk in [full_answer[i:i + 20] for i in range(0, len(full_answer), 20)]:
            payload = json.dumps({"query_id": query_id, "content": chunk, "finish_reason": None}, ensure_ascii=False)
            yield f"event: delta\ndata: {payload}\n\n"
            await asyncio.sleep(0.05)

    if mode_used == "kg_only":
        sources = []
    record = QARecord(query_id=query_id, doc_id=doc_id, user_id=user_id, question=question,
                      answer=full_answer, retrieval_mode=mode_used, retrieval_mode_used=mode_used,
                      input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                      sources_json=json.dumps(sources, ensure_ascii=False))
    db.add(record)
    await db.commit()
    done_payload = json.dumps({
        "query_id": query_id, "content": "", "finish_reason": "stop",
        "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
        "retrieval_mode_used": mode_used, "kg_nodes_used": len(kg["nodes"]), "kg_edges_used": len(kg["edges"]), "sources": sources
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
    mode_used = _normalize_mode(retrieval_mode, kg)
    doc_title = doc.original_name or doc_id
    if mode_used == "agentic":
        context, sources, _ = await _agentic_retrieve(user_id, question, doc_id, doc_title, kg, db=db)
    else:
        context, sources, mode_used = _build_retrieval_context(
            kg, _load_chunks(doc_id), question, mode_used, doc_id=doc_id, doc_title=doc_title
        )

    deepseek_key = await key_vault_service.get_verified_secret(db, user_id, "deepseek")
    if not settings.MOCK_EXTERNAL_SERVICES and llm_client.llm_available(deepseek_key):
        messages = [
            {"role": "system", "content": _system_prompt_for_mode(mode_used)},
            {"role": "user", "content": f"{context}\n\n用户问题: {question}"},
        ]
        try:
            full_answer, usage = await llm_client.chat_complete(deepseek_key, messages, temperature=0.2, max_tokens=1500)
        except Exception as e:
            raise ValueError(f"5002:LLM调用失败: {e}")
        if not full_answer.strip():
            full_answer = "根据现有文档未找到相关信息。" if mode_used == "agentic" else "根据现有知识图谱未找到相关信息。"
    else:
        # KG-Only：只把命中的两跳子图交给 mock/LLM，不注入原文
        subgraph_for_ans = _select_kg_for_question(kg, question) if mode_used == "kg_only" else kg
        full_answer = _mock_answer(question, subgraph_for_ans)
        if mode_used == "agentic" and sources:
            full_answer += "\n\n**混合检索补充（原文片段）**\n" + "\n".join(
                f"- {s['excerpt']}" for s in sources[:2]
            )
        usage = {"input_tokens": len(question) * 2, "output_tokens": len(full_answer)}

    query_id = str(uuid.uuid4())
    if mode_used == "kg_only":
        sources = []
    record = QARecord(query_id=query_id, doc_id=doc_id, user_id=user_id, question=question,
                      answer=full_answer, retrieval_mode=mode_used, retrieval_mode_used=mode_used,
                      input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                      sources_json=json.dumps(sources, ensure_ascii=False))
    db.add(record)
    await db.commit()
    return {"query_id": query_id, "answer": full_answer, "retrieval_mode_used": mode_used,
            "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
            "kg_nodes_used": len(kg["nodes"]), "kg_edges_used": len(kg["edges"]), "sources": sources}

async def kb_qa_stream(db: AsyncSession, kb_id: str, doc_ids: list[str], question: str, user_id: str, retrieval_mode: str = "auto") -> AsyncGenerator[str, None]:
    query_id = str(uuid.uuid4())
    deepseek_key = await key_vault_service.get_verified_secret(db, user_id, "deepseek")

    contexts: list[str] = []
    sources: list[dict] = []
    docs_meta: list[tuple[str, str, dict]] = []
    total_nodes = 0
    for doc_id in doc_ids[:10]:
        kp = _kg_path(doc_id)
        kg = json.loads(kp.read_text(encoding="utf-8")) if kp.exists() else {"nodes": [], "edges": []}
        total_nodes += len(kg.get("nodes") or [])
        result_doc = await db.execute(select(Document).where(Document.doc_id == doc_id))
        doc = result_doc.scalar_one_or_none()
        title = doc.original_name if doc else doc_id
        docs_meta.append((doc_id, title, kg))

    mode_used = _normalize_mode(retrieval_mode, {"nodes": [{"id": i} for i in range(total_nodes)]})

    for doc_id, title, kg in docs_meta:
        if mode_used == "kg_only":
            subgraph = _select_kg_for_question(kg, question)
            if subgraph["nodes"] or subgraph["edges"]:
                contexts.append(f"【文档: {title} 知识图谱】\n{_kg_summary(subgraph)}")
                # KG-Only 无原文溯源：不生成引用来源
        else:
            chunks = _load_chunks(doc_id)
            retrieved = _retrieve_chunks(question, chunks, top_k=3)
            if retrieved:
                contexts.append(f"【文档: {title}】\n" + "\n".join(c["text"] for c in retrieved))
                sources.append(_chunk_to_source(retrieved[0], doc_id, title))
            elif kg.get("nodes"):
                subgraph = _select_kg_for_question(kg, question)
                contexts.append(f"【文档: {title} 知识图谱】\n{_kg_summary(subgraph)}")
                node_txt = "、".join(n.get("label", "") for n in subgraph["nodes"][:10])
                sources.append({
                    "doc_id": doc_id, "doc_name": title, "doc_title": title,
                    "page": 1, "excerpt": node_txt, "snippet": node_txt,
                })

    if not settings.MOCK_EXTERNAL_SERVICES and llm_client.llm_available(deepseek_key):
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
        mock_sources = []
        for doc_id, title, kg in docs_meta:
            if not kg.get("nodes"):
                continue
            subgraph_for_ans = _select_kg_for_question(kg, question) if mode_used == "kg_only" else kg
            ans = _mock_answer(question, subgraph_for_ans)
            answers.append(ans)
            if mode_used == "agentic":
                mock_sources.append({
                    "doc_id": doc_id, "doc_name": title, "doc_title": title,
                    "page": 1, "excerpt": ans[:80] + "...", "snippet": ans[:80] + "...",
                })
        sources = mock_sources or (sources if mode_used == "agentic" else [])
        full_answer = f"联合分析 {len(doc_ids)} 份文档后的综合回答：\n\n" + "\n\n---\n\n".join(answers[:3]) if answers else "未找到相关信息"
        if mode_used == "agentic" and sources:
            full_answer += "\n\n（已附引用来源）"
        if mode_used == "kg_only":
            sources = []
        usage = {"input_tokens": len(question) * 3, "output_tokens": len(full_answer)}
        for chunk in [full_answer[i:i + 20] for i in range(0, len(full_answer), 20)]:
            payload = json.dumps({"query_id": query_id, "content": chunk, "finish_reason": None}, ensure_ascii=False)
            yield f"event: delta\ndata: {payload}\n\n"
            await asyncio.sleep(0.05)

    if mode_used == "kg_only":
        sources = []
    record = QARecord(query_id=query_id, kb_id=kb_id, user_id=user_id, question=question,
                      answer=full_answer, retrieval_mode=mode_used, retrieval_mode_used=mode_used,
                      input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                      sources_json=json.dumps(sources, ensure_ascii=False))
    db.add(record)
    await db.commit()
    done_payload = json.dumps({
        "query_id": query_id, "content": "", "finish_reason": "stop",
        "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
        "retrieval_mode_used": mode_used, "sources": sources
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
