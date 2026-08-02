from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any

class QAOptions(BaseModel):
    retrieval_mode: str = "kg_only"
    max_tokens: int = 1024
    temperature: float = 0.0

class QARequest(BaseModel):
    doc_id: str
    question: str
    stream: bool = False
    options: QAOptions = QAOptions()

class KBQARequest(BaseModel):
    kb_id: str
    doc_ids: list[str]
    question: str
    stream: bool = False
    options: QAOptions = QAOptions()

class FeedbackRequest(BaseModel):
    rating: str  # positive | negative
    comment: Optional[str] = None

class QAHistoryOut(BaseModel):
    query_id: str
    doc_id: Optional[str]
    kb_id: Optional[str]
    question: str
    answer: str
    retrieval_mode: str
    input_tokens: int
    output_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}
