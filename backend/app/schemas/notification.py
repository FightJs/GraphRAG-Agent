from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NotificationPreferencesOut(BaseModel):
    index_completed: bool = True
    index_failed: bool = True
    qa_weekly_digest: bool = True


class NotificationPreferencesUpdate(BaseModel):
    index_completed: Optional[bool] = None
    index_failed: Optional[bool] = None
    qa_weekly_digest: Optional[bool] = None


class NotificationOut(BaseModel):
    notification_id: str
    type: str
    title: str
    body: str = ""
    related_id: Optional[str] = None
    is_read: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class UnreadCountOut(BaseModel):
    unread: int = Field(ge=0)
