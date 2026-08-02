"""知识图谱抽取 — 调用 LLM 从文档分块中抽取实体与关系，合并为单张图"""
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime

from app.services import llm_client

logger = logging.getLogger(__name__)

MAX_CHUNKS_FOR_KG = 8  # 控制单文档抽取的 LLM 调用次数上限

_SYSTEM_PROMPT = """你是专业的知识图谱抽取引擎。给定一段文档文本，抽取其中的实体和关系，严格按以下 JSON 格式输出，不要输出任何多余文字：

{
  "nodes": [
    {"local_id": "n1", "label": "实体名称", "type": "实体类型（如 PERSON/SKILL/PROJECT/COMPANY/SCHOOL/POSITION/CONCEPT/LOCATION/DATE/OTHER，用最贴切的大写英文单词）", "attributes": {"任意补充信息": "值"}}
  ],
  "edges": [
    {"source": "n1", "target": "n2", "relation": "关系描述（简短中文动词短语，如 掌握/就职于/毕业于/属于）"}
  ]
}

要求：
- 每个 node 的 local_id 只在本段文本内唯一即可（如 n1, n2, n3...）
- 只抽取文本中明确出现的实体和关系，不要编造
- 如果文本中没有可抽取的实体，返回 {"nodes": [], "edges": []}
"""


def _try_recover_json(content: str) -> dict | None:
    """尝试从截断的 JSON 字符串中抢救已完整的 nodes/edges 数组"""
    import re
    try:
        # 尝试直接解析
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # 截断发生在 nodes 数组中间——尝试提取已完整的元素
    nodes, edges = [], []
    nodes_match = re.search(r'"nodes"\s*:\s*(\[.*?\])', content, re.DOTALL)
    if nodes_match:
        try:
            nodes = json.loads(nodes_match.group(1))
        except json.JSONDecodeError:
            # 数组本身也截断了，取到最后一个完整的 } 为止
            raw = nodes_match.group(1)
            last_close = raw.rfind('}')
            if last_close > 0:
                try:
                    nodes = json.loads(raw[:last_close + 1] + ']')
                except json.JSONDecodeError:
                    pass
    edges_match = re.search(r'"edges"\s*:\s*(\[.*?\])', content, re.DOTALL)
    if edges_match:
        try:
            edges = json.loads(edges_match.group(1))
        except json.JSONDecodeError:
            pass
    if nodes or edges:
        logger.warning("JSON was truncated; recovered %d nodes, %d edges", len(nodes), len(edges))
        return {"nodes": nodes, "edges": edges}
    return None


async def _extract_chunk(chunk_text: str) -> dict:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": chunk_text[:4000]},
    ]
    try:
        content, _usage = await llm_client.chat_complete(
            messages, temperature=0.0, max_tokens=4096, response_format_json=True
        )
        logger.debug("LLM raw response (%d chars): %s", len(content), content[:200])
        data = _try_recover_json(content)
        if data is None:
            logger.error("KG extraction: could not parse LLM response: %s", content[:300])
            return {"nodes": [], "edges": []}
        if not isinstance(data, dict):
            logger.warning("LLM returned non-dict: %r", data)
            return {"nodes": [], "edges": []}
        return {"nodes": data.get("nodes") or [], "edges": data.get("edges") or []}
    except Exception as exc:
        logger.error("KG extraction chunk failed: %s", exc, exc_info=True)
        return {"nodes": [], "edges": []}


def _merge_chunk_results(chunk_results: list[dict]) -> dict:
    """将多个 chunk 的局部抽取结果合并为全局图，按 (type, label) 去重节点"""
    merged_nodes: dict[tuple[str, str], dict] = {}
    node_id_map: dict[tuple[str, str], str] = {}
    type_counters: dict[str, int] = defaultdict(int)
    edges_seen: set[tuple[str, str, str]] = set()
    merged_edges: list[dict] = []

    for result in chunk_results:
        local_to_global: dict[str, str] = {}
        for node in result["nodes"]:
            label = str(node.get("label", "")).strip()
            ntype = str(node.get("type", "OTHER")).strip().upper() or "OTHER"
            if not label:
                continue
            key = (ntype, label)
            if key not in merged_nodes:
                type_counters[ntype] += 1
                global_id = f"{ntype.lower()}_{type_counters[ntype]}_{uuid.uuid4().hex[:6]}"
                node_id_map[key] = global_id
                merged_nodes[key] = {
                    "id": global_id,
                    "label": label,
                    "type": ntype,
                    "attributes": node.get("attributes") or {},
                }
            local_id = node.get("local_id")
            if local_id:
                local_to_global[str(local_id)] = node_id_map[key]

        for edge in result["edges"]:
            src = local_to_global.get(str(edge.get("source", "")))
            tgt = local_to_global.get(str(edge.get("target", "")))
            relation = str(edge.get("relation", "")).strip()
            if not src or not tgt or not relation or src == tgt:
                continue
            edge_key = (src, tgt, relation)
            if edge_key in edges_seen:
                continue
            edges_seen.add(edge_key)
            merged_edges.append({"id": str(uuid.uuid4()), "source": src, "target": tgt, "relation": relation})

    return {"nodes": list(merged_nodes.values()), "edges": merged_edges}


async def extract_kg(doc_id: str, chunks: list[str]) -> dict:
    """对文档分块逐个调用 LLM 抽取，合并为知识图谱 JSON"""
    selected = chunks[:MAX_CHUNKS_FOR_KG]
    chunk_results = []
    for chunk_text in selected:
        if not chunk_text.strip():
            continue
        chunk_results.append(await _extract_chunk(chunk_text))
    merged = _merge_chunk_results(chunk_results)
    return {
        "doc_id": doc_id,
        "nodes": merged["nodes"],
        "edges": merged["edges"],
        "meta": {
            "total_nodes": len(merged["nodes"]),
            "total_edges": len(merged["edges"]),
            "created_at": datetime.utcnow().isoformat() + "Z",
        },
    }
