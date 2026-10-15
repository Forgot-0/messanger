import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.repositories.blocks import ChatUserBlockRepository
from app.core.commands import BaseCommand, BaseCommandHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApplyUserBlockCommand(BaseCommand):
    owner_id: int
    target_id: int
    blocked: bool


@dataclass(frozen=True)
class ApplyUserBlockCommandHandler(BaseCommandHandler[ApplyUserBlockCommand, None]):
    session: AsyncSession
    block_repository: ChatUserBlockRepository

    async def handle(self, command: ApplyUserBlockCommand) -> None:
        if command.blocked:
            changed = await self.block_repository.block(command.owner_id, command.target_id)
        else:
            changed = await self.block_repository.unblock(command.owner_id, command.target_id)

        await self.session.commit()

        logger.info(
            "Block projection applied",
            extra={
                "owner_id": command.owner_id,
                "target_id": command.target_id,
                "blocked": command.blocked,
                "changed": changed,
            },
        )
