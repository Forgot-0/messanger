import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.exceptions import NotFoundContactError
from app.profiles.repositories.contacts import ContactRepository
from app.profiles.services.contact_access import check_contact_owner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoveContactCommand(BaseCommand):
    owner_id: int
    contact_id: int

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class RemoveContactCommandHandler(BaseCommandHandler[RemoveContactCommand, None]):
    session: AsyncSession
    contact_repository: ContactRepository
    rbac_manager: RBACManagerInterface
    event_bus: BaseEventBus

    async def handle(self, command: RemoveContactCommand) -> None:
        check_contact_owner(self.rbac_manager, command.owner_id, command.user_jwt_data)

        contact = await self.contact_repository.get(command.owner_id, command.contact_id)
        if contact is None:
            raise NotFoundContactError(contact_id=command.contact_id)

        contact.register_removed()
        events = contact.pull_events()

        await self.contact_repository.delete(command.owner_id, command.contact_id)

        await self.event_bus.publish(events)
        await self.session.commit()

        logger.info(
            "Contact removed",
            extra={"owner_id": command.owner_id, "contact_id": command.contact_id},
        )
