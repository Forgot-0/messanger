import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.repositories.privacy import ChatPrivacyProjectionRepository
from app.core.commands import BaseCommand, BaseCommandHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApplyProfilePrivacyCommand(BaseCommand):
    user_id: int
    event_updated_at: datetime
    rules: dict[str, str] = field(default_factory=dict)
    exceptions: dict[str, dict[str, list[int]]] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplyProfilePrivacyCommandHandler(
    BaseCommandHandler[ApplyProfilePrivacyCommand, None]
):
    session: AsyncSession
    privacy_repository: ChatPrivacyProjectionRepository

    async def handle(self, command: ApplyProfilePrivacyCommand) -> None:
        applied = await self.privacy_repository.upsert_privacy(
            user_id=command.user_id,
            rules=command.rules,
            source_updated_at=command.event_updated_at,
        )

        if applied:
            await self.privacy_repository.replace_exceptions(
                command.user_id, command.exceptions
            )

        await self.session.commit()

        logger.info(
            "Privacy projection applied" if applied else "Privacy projection event skipped (stale)",
            extra={"user_id": command.user_id},
        )
