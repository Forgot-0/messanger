from typing import Any, Self
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin


class OutboxMessage(BaseModel, DateMixin):
    __tablename__ = "outbox_messages"

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), primary_key=True)

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
        event_id: UUID,
        event_name: str,
        aggregate_type: str,
        aggregate_id: str,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
    ) -> Self:
        return cls(
            id=event_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_name=event_name,
            topic=topic,
            payload=payload,
            headers=headers or {},
        )
