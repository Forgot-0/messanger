import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.dtos.contacts import UserContactDTO
from app.profiles.exceptions import NotFoundContactError
from app.profiles.repositories.contacts import ContactRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.contact_access import check_contact_owner
from app.profiles.services.privacy import ProfilePrivacyService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateContactCommand(BaseCommand):
    owner_id: int
    contact_id: int

    first_name: str | None = None
    last_name: str | None = None
    is_favorite: bool | None = None

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class UpdateContactCommandHandler(BaseCommandHandler[UpdateContactCommand, UserContactDTO]):
    session: AsyncSession
    contact_repository: ContactRepository
    rbac_manager: RBACManagerInterface
    avatar_url_service: ProfileAvatarUrlService
    privacy_service: ProfilePrivacyService

    async def handle(self, command: UpdateContactCommand) -> UserContactDTO:
        check_contact_owner(self.rbac_manager, command.owner_id, command.user_jwt_data)

        contact = await self.contact_repository.get(
            command.owner_id, command.contact_id, with_profile=True
        )
        if contact is None:
            raise NotFoundContactError(contact_id=command.contact_id)

        contact.rename(command.first_name, command.last_name)

        if command.is_favorite is not None:
            contact.mark_favorite(command.is_favorite)

        await self.session.commit()

        logger.info(
            "Contact updated",
            extra={"owner_id": command.owner_id, "contact_id": command.contact_id},
        )

        dto = UserContactDTO.model_validate(contact)
        await self.privacy_service.hide_photos(command.owner_id, [dto.profile])
        await self.avatar_url_service.attach([dto.profile])

        return dto
