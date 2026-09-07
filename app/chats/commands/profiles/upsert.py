import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.avatars import pick_avatar_key
from app.chats.repositories.user_profile import ChatUserProfileRepository
from app.core.commands import BaseCommand, BaseCommandHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpsertProfileProjectionCommand(BaseCommand):
    user_id: int
    username: str | None = None
    display_name: str | None = None
    avatars: dict[Any, dict[str, str]] = field(default_factory=dict)

    event_id: UUID | None = None
    event_updated_at: datetime | None = None


@dataclass(frozen=True)
class UpsertProfileProjectionCommandHandler(
    BaseCommandHandler[UpsertProfileProjectionCommand, None]
):
    session: AsyncSession
    profile_repository: ChatUserProfileRepository

    async def handle(self, command: UpsertProfileProjectionCommand) -> None:
        if command.event_updated_at is None:
            logger.warning(
                "Profile projection event without timestamp, skipping",
                extra={"user_id": command.user_id, "event_id": str(command.event_id)},
            )
            return

        applied = await self.profile_repository.upsert(
            user_id=command.user_id,
            username=command.username,
            display_name=command.display_name,
            avatar_s3_key=pick_avatar_key(command.avatars),
            source_updated_at=command.event_updated_at,
            event_id=command.event_id,
        )
        await self.session.commit()

        if applied:
            logger.info(
                "Profile projection updated",
                extra={"user_id": command.user_id, "event_id": str(command.event_id)},
            )
        else:
            logger.info(
                "Profile projection event skipped (stale or duplicate)",
                extra={"user_id": command.user_id, "event_id": str(command.event_id)},
            )
