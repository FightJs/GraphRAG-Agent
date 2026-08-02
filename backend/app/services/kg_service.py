import json, uuid
from pathlib import Path
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.db_models import Document

def _kg_path(doc_id: str) -> Path:
    return Path(settings.KG_DIR) / f"{doc_id}.json"

async def get_kg(db: AsyncSession, doc_id: str, owner_id: str) -> dict:
    result = await db.execute(select(Document).where(Document.doc_id == doc_id, Document.owner_id == owner_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("4041:文档不存在")
    if doc.status != "indexed":
        raise ValueError("4043:文档尚未完成索引")
    kp = _kg_path(doc_id)
    if not kp.exists():
        raise ValueError("4043:KG数据不存在")
    return json.loads(kp.read_text(encoding="utf-8"))

async def apply_kg_operations(db: AsyncSession, doc_id: str, owner_id: str, operations: list[dict]) -> dict:
    result = await db.execute(select(Document).where(Document.doc_id == doc_id, Document.owner_id == owner_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("4041:文档不存在")
    if doc.status != "indexed":
        raise ValueError("4031:无权限编辑该文档的知识图谱")
    kg = json.loads(_kg_path(doc_id).read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in kg["nodes"]}
    edges = {e["id"]: e for e in kg["edges"]}
    applied = 0
    skipped = 0
    VALID_OPS = {"add_node","update_node","delete_node","add_edge","update_edge","delete_edge"}
    for op_data in operations:
        op = op_data.get("op")
        if op not in VALID_OPS:
            raise ValueError(f"4222:op字段值非法，应为 {'/'.join(VALID_OPS)}")
        if op == "add_node":
            node = op_data["node"]
            if node["id"] in nodes:
                skipped += 1
            else:
                nodes[node["id"]] = node
                applied += 1
        elif op == "update_node":
            nid = op_data["node_id"]
            if nid not in nodes:
                skipped += 1
            else:
                nodes[nid].update(op_data.get("patch", {}))
                applied += 1
        elif op == "delete_node":
            nid = op_data["node_id"]
            if nid in nodes:
                del nodes[nid]
                edges = {eid: e for eid, e in edges.items() if e["source"] != nid and e["target"] != nid}
                applied += 1
            else:
                skipped += 1
        elif op == "add_edge":
            edge = op_data["edge"]
            eid = edge.get("id", str(uuid.uuid4()))
            edge["id"] = eid
            if eid in edges:
                skipped += 1
            else:
                edges[eid] = edge
                applied += 1
        elif op == "update_edge":
            eid = op_data["edge_id"]
            if eid not in edges:
                skipped += 1
            else:
                edges[eid].update(op_data.get("patch", {}))
                applied += 1
        elif op == "delete_edge":
            eid = op_data["edge_id"]
            if eid in edges:
                del edges[eid]
                applied += 1
            else:
                skipped += 1
    kg["nodes"] = list(nodes.values())
    kg["edges"] = list(edges.values())
    now = datetime.utcnow().isoformat() + "Z"
    kg["meta"] = {"total_nodes": len(kg["nodes"]), "total_edges": len(kg["edges"]), "last_edited_at": now}
    _kg_path(doc_id).write_text(json.dumps(kg, ensure_ascii=False, indent=2))
    doc.node_count = len(kg["nodes"])
    doc.edge_count = len(kg["edges"])
    doc.kg_edited_at = datetime.utcnow()
    await db.commit()
    return {"doc_id": doc_id, "applied_ops": applied, "skipped_ops": skipped, "meta": kg["meta"]}
