import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.exceptions import SelfContactError
from app.profiles.models.contacts import BlockedUser
from app.profiles.repositories.contacts import BlockedUserRepository
from app.profiles.services.contact_access import check_contact_owner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockUserCommand(BaseCommand):
    owner_id: int
    target_id: int

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class BlockUserCommandHandler(BaseCommandHandler[BlockUserCommand, None]):
    session: AsyncSession
    blocked_repository: BlockedUserRepository
    rbac_manager: RBACManagerInterface
    event_bus: BaseEventBus

    async def handle(self, command: BlockUserCommand) -> None:
        check_contact_owner(self.rbac_manager, command.owner_id, command.user_jwt_data)

        if command.owner_id == command.target_id:
            raise SelfContactError

        existing = await self.blocked_repository.get(command.owner_id, command.target_id)
        if existing is not None:
            return

        blocked = BlockedUser.create(owner_id=command.owner_id, target_id=command.target_id)
        self.session.add(blocked)

        await self.event_bus.publish(blocked.pull_events())
        await self.session.commit()
        await self.blocked_repository.invalidate_block_list(command.owner_id)

        logger.info(
            "User blocked",
            extra={"owner_id": command.owner_id, "target_id": command.target_id},
        )
