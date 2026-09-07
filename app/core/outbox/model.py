from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid7

from sqlalchemy import (
    UUID as SAUUID,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxMessage(BaseModel, DateMixin):
    __tablename__ = "outbox_messages"

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), primary_key=True, default=uuid7)

    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)

    event_name: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )

    @classmethod
    def create(
        cls,
        *,
        aggregate_id: str,
        event_name: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
    ) -> Self:
        return cls(
            id=uuid7(),
            aggregate_type=event_name.split(".")[1],
            aggregate_id=aggregate_id,
            event_name=event_name,
            topic=event_name.split(".", maxsplit=1)[0],
            payload=payload,
            headers=headers or {},
        )
