from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderName = Literal["deepseek", "mineru", "embedding"]


class ApiKeyUpsert(BaseModel):
    api_key: str = Field(min_length=8, max_length=4096)


class ProviderStatus(BaseModel):
    provider: ProviderName
    configured: bool
    is_verified: bool
    key_hint: str | None = None
    verified_at: datetime | None = None


class ApiKeyStatusResponse(BaseModel):
    providers: list[ProviderStatus]
    ready: bool
