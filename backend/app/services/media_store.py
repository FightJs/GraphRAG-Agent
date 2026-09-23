"""媒体存储路径与 DOCUMENT 节点共用工具（SPEC-TABLE / SPEC-IMAGE 共享契约）"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.config import settings


def doc8(doc_id: str) -> str:
    return (doc_id or "")[:8]


def media_root(doc_id: str) -> Path:
    return Path(settings.MEDIA_DIR) / doc_id


def tables_dir(doc_id: str) -> Path:
    return media_root(doc_id) / "tables"


def images_dir(doc_id: str) -> Path:
    return media_root(doc_id) / "images"


def table_json_path(doc_id: str, table_id: str) -> Path:
    return tables_dir(doc_id) / f"{table_id}.json"


def image_path(doc_id: str, image_id: str, ext: str) -> Path:
    ext = (ext or ".png").lstrip(".") or "png"
    return images_dir(doc_id) / f"{image_id}.{ext}"


def image_meta_path(doc_id: str, image_id: str) -> Path:
    return images_dir(doc_id) / f"{image_id}.meta.json"


def manifest_path(doc_id: str) -> Path:
    return media_root(doc_id) / "manifest.json"


def write_manifest(doc_id: str, tables: list[str], images: list[str]) -> None:
    path = manifest_path(doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tables": tables, "images": images}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_table_brief(doc_id: str, table_id: str) -> str:
    p = table_json_path(doc_id, table_id)
    if not p.exists():
        return ""
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    summary = rec.get("summary") or rec.get("llm_summary") or ""
    headers = rec.get("headers") or []
    rows = rec.get("rows") or []
    parts = [f"[表格 {table_id}]"]
    if summary:
        parts.append(f"摘要: {summary}")
    if headers:
        parts.append("表头: " + " | ".join(str(h) for h in headers))
    for row in rows[:8]:
        cells = row if isinstance(row, list) else list(row.values()) if isinstance(row, dict) else [row]
        parts.append(" | ".join(str(c) for c in cells))
    if len(rows) > 8:
        parts.append(f"...（共 {len(rows)} 行）")
    return "\n".join(parts)


def _load_image_brief(doc_id: str, image_id: str) -> str:
    p = image_meta_path(doc_id, image_id)
    if not p.exists():
        return f"[图片 {image_id}]"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return f"[图片 {image_id}]"
    final = meta.get("final_text") or meta.get("ocr_text") or meta.get("description") or meta.get("caption") or ""
    caption = meta.get("caption") or ""
    parts = [f"[图片 {image_id}]"]
    if caption:
        parts.append(f"图注: {caption}")
    if final:
        parts.append(f"内容: {final[:400]}")
    return " ".join(parts) if len(parts) > 1 else parts[0]


def expand_placeholders(doc_id: str, text: str) -> str:
    """将 {{TABLE:id}} / {{IMAGE:id}} 展开为可读摘要，供 LLM 上下文使用。"""
    import re
    if not text:
        return ""

    def _table(m):
        return _load_table_brief(doc_id, m.group(1))

    def _image(m):
        return _load_image_brief(doc_id, m.group(1))

    out = re.sub(r"\{\{TABLE:([^}]+)\}\}", _table, text)
    out = re.sub(r"\{\{IMAGE:([^}]+)\}\}", _image, out)
    return out











def ensure_document_node(kg: dict, doc_id: str, original_name: str = "") -> dict:
    """保证 KG 中存在 DOCUMENT 根节点，返回 kg。"""
    if not isinstance(kg, dict):
        kg = {"doc_id": doc_id, "nodes": [], "edges": [], "meta": {}}
    nodes = kg.setdefault("nodes", [])
    kg.setdefault("edges", [])
    kg.setdefault("meta", {})
    doc_node_id = f"doc_{doc8(doc_id)}"
    for node in nodes:
        if node.get("type") == "DOCUMENT" or node.get("id") == doc_node_id:
            return kg
    nodes.insert(
        0,
        {
            "id": doc_node_id,
            "label": original_name or doc_id,
            "type": "DOCUMENT",
            "attributes": {
                "doc_id": doc_id,
                "file_format": "PDF",
            },
        },
    )
    return kg


def find_document_node_id(kg: dict, doc_id: str) -> str | None:
    doc_node_id = f"doc_{doc8(doc_id)}"
    for node in kg.get("nodes") or []:
        if node.get("type") == "DOCUMENT" or node.get("id") == doc_node_id:
            return node.get("id") or doc_node_id
    return None


def new_edge(source: str, target: str, relation: str) -> dict:
    return {"id": str(uuid.uuid4()), "source": source, "target": target, "relation": relation}
