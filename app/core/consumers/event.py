from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TypedEventDTO[PayloadT: BaseModel](BaseModel):
    event_name: str
    event_id: UUID
    payload: PayloadT
    headers: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DictEventDTO(BaseModel):
    event_name: str
    event_id: UUID
    payload: dict[str, Any]
    headers: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
