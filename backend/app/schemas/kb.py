from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class KBCreate(BaseModel):
    name: str
    description: str = ""
    color: str = "blue"
    icon: str = "database"

class KBUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None

class KBOut(BaseModel):
    kb_id: str
    name: str
    description: str
    color: str
    icon: str = "database"
    owner_id: str
    doc_count: int = 0
    indexed_count: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
