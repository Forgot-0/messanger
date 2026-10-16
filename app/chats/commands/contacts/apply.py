import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.repositories.privacy import ChatPrivacyProjectionRepository
from app.core.commands import BaseCommand, BaseCommandHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApplyUserContactCommand(BaseCommand):
    owner_id: int
    contact_id: int
    added: bool


@dataclass(frozen=True)
class ApplyUserContactCommandHandler(BaseCommandHandler[ApplyUserContactCommand, None]):
    session: AsyncSession
    privacy_repository: ChatPrivacyProjectionRepository

    async def handle(self, command: ApplyUserContactCommand) -> None:
        if command.added:
            changed = await self.privacy_repository.add_contact(
                command.owner_id, command.contact_id
            )
        else:
            changed = await self.privacy_repository.remove_contact(
                command.owner_id, command.contact_id
            )

        await self.session.commit()

        logger.info(
            "Contact projection applied",
            extra={
                "owner_id": command.owner_id,
                "contact_id": command.contact_id,
                "added": command.added,
                "changed": changed,
            },
        )
