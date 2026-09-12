import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.config import profile_config
from app.profiles.dtos.contacts import UserContactDTO
from app.profiles.exceptions import (
    ContactBlockedError,
    ContactLimitExceededError,
    NotFoundContactError,
    NotFoundContactTargetError,
    SelfContactError,
)
from app.profiles.models.contacts import ContactSource, UserContact
from app.profiles.repositories.contacts import BlockedUserRepository, ContactRepository
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.contact_access import check_contact_owner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddContactCommand(BaseCommand):
    owner_id: int

    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class AddContactCommandHandler(BaseCommandHandler[AddContactCommand, UserContactDTO]):
    session: AsyncSession
    contact_repository: ContactRepository
    profile_repository: ProfileRepository
    blocked_repository: BlockedUserRepository
    rbac_manager: RBACManagerInterface
    event_bus: BaseEventBus

    async def handle(self, command: AddContactCommand) -> UserContactDTO:
        check_contact_owner(self.rbac_manager, command.owner_id, command.user_jwt_data)

        profile = None

        if command.username is not None:
            profile = await self.profile_repository.get_by_username(command.username)
        elif command.user_id is not None:
            profile = (await self.profile_repository.get_by_ids([command.user_id])).get(
                command.user_id
            )

        if profile is None:
            raise NotFoundContactTargetError(user_id=command.user_id, username=command.username)

        if profile.id == command.owner_id:
            raise SelfContactError

        blocked = await self.blocked_repository.get_block_list(command.owner_id)
        if profile.id in blocked:
            raise ContactBlockedError(user_id=profile.id)

        contact = await self.contact_repository.get(command.owner_id, profile.id)
        reverse = await self.contact_repository.find_reverse_owners(command.owner_id, [profile.id])
        is_mutual = profile.id in reverse

        if contact is None:
            if await self.contact_repository.count(command.owner_id) >= profile_config.MAX_CONTACTS_PER_USER:
                raise ContactLimitExceededError(limit=profile_config.MAX_CONTACTS_PER_USER)

            contact = UserContact.create(
                owner_id=command.owner_id,
                contact_id=profile.id,
                source=ContactSource.USERNAME if command.username else ContactSource.MANUAL,
                first_name=command.first_name,
                last_name=command.last_name,
                is_mutual=is_mutual,
            )
            self.session.add(contact)
        else:
            contact.rename(
                command.first_name or contact.first_name,
                command.last_name or contact.last_name,
            )

        await self.session.flush()

        if is_mutual:
            await self.contact_repository.set_mutual(command.owner_id, [profile.id])

        await self.event_bus.publish(contact.pull_events())
        await self.session.commit()

        logger.info(
            "Contact added",
            extra={
                "owner_id": command.owner_id,
                "contact_id": profile.id,
                "is_mutual": is_mutual,
            },
        )

        contact = await self.contact_repository.get(command.owner_id, profile.id, with_profile=True)

        if contact is None:
            raise NotFoundContactError(contact_id=profile.id)

        return UserContactDTO.model_validate(contact)

