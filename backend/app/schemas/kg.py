from pydantic import BaseModel
from typing import Any, Optional

class KGNode(BaseModel):
    id: str
    label: str
    type: str
    attributes: dict[str, Any] = {}

class KGEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str

class KGGraph(BaseModel):
    doc_id: str
    nodes: list[KGNode]
    edges: list[KGEdge]
    meta: dict[str, Any]

class KGOperation(BaseModel):
    op: str  # add_node|update_node|delete_node|add_edge|update_edge|delete_edge
    node: Optional[dict] = None
    node_id: Optional[str] = None
    edge: Optional[dict] = None
    edge_id: Optional[str] = None
    patch: Optional[dict] = None

class KGEditRequest(BaseModel):
    operations: list[KGOperation]
