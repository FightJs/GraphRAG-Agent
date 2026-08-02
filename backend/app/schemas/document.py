from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class DocOut(BaseModel):
    doc_id: str
    kb_id: Optional[str]
    filename: str
    original_name: str
    file_format: str
    status: str
    file_size: int
    page_count: int
    node_count: int
    edge_count: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class TaskOut(BaseModel):
    task_id: str
    doc_id: str
    status: str
    progress: int
    stages: list
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
