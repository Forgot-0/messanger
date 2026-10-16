from dataclasses import dataclass
from datetime import datetime

from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.config import profile_config
from app.profiles.dtos.contacts import ContactListDTO, UserContactDTO
from app.profiles.repositories.contacts import BlockedUserRepository, ContactRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.contact_access import check_contact_owner
from app.profiles.services.privacy import ProfilePrivacyService


@dataclass(frozen=True)
class GetContactsQuery(BaseQuery):
    owner_id: int

    limit: int = profile_config.CONTACTS_PAGE_SIZE
    after_contact_id: int | None = None
    updated_after: datetime | None = None

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class GetContactsQueryHandler(BaseQueryHandler[GetContactsQuery, ContactListDTO]):
    contact_repository: ContactRepository
    blocked_repository: BlockedUserRepository
    rbac_manager: RBACManagerInterface
    avatar_url_service: ProfileAvatarUrlService
    privacy_service: ProfilePrivacyService

    async def handle(self, query: GetContactsQuery) -> ContactListDTO:
        check_contact_owner(self.rbac_manager, query.owner_id, query.user_jwt_data)

        limit = min(max(query.limit, 1), profile_config.CONTACTS_MAX_PAGE_SIZE)
        rows, has_next = await self.contact_repository.list_page(
            owner_id=query.owner_id,
            limit=limit,
            after_contact_id=query.after_contact_id,
            updated_after=query.updated_after,
        )

        contacts = [UserContactDTO.model_validate(contact) for contact in rows]

        hidden = await self.blocked_repository.blockers_of(
            query.owner_id, [contact.contact_id for contact in contacts]
        )
        for contact in contacts:
            if contact.contact_id in hidden and contact.profile is not None:
                contact.profile.avatars = {}

        await self.privacy_service.hide_photos(
            query.owner_id, [contact.profile for contact in contacts]
        )
        await self.avatar_url_service.attach(contact.profile for contact in contacts)

        version = None if has_next else await self.contact_repository.max_updated_at(query.owner_id)

        return ContactListDTO(
            contacts=contacts,
            has_next=has_next,
            next_contact_id=contacts[-1].contact_id if has_next and contacts else None,
            version=version,
        )
