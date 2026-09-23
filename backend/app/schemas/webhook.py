from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional

class WebhookCreate(BaseModel):
    url: str
    events: list[str]
    secret: Optional[str] = None

class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    events: Optional[list[str]] = None
    is_active: Optional[bool] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None
    secret: Optional[str] = None

class WebhookOut(BaseModel):
    webhook_id: str
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
