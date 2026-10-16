from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.config import profile_config
from app.profiles.dtos.contacts import (
    ContactProfileDTO,
    ContactSearchDTO,
    ContactSearchItemDTO,
    UserContactDTO,
)
from app.profiles.repositories.contacts import BlockedUserRepository, ContactRepository
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.contact_access import check_contact_owner
from app.profiles.services.privacy import ProfilePrivacyService


@dataclass(frozen=True)
class SearchContactsQuery(BaseQuery):
    owner_id: int
    query: str

    limit: int = profile_config.CONTACTS_SEARCH_LIMIT
    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class SearchContactsQueryHandler(BaseQueryHandler[SearchContactsQuery, ContactSearchDTO]):
    contact_repository: ContactRepository
    profile_repository: ProfileRepository
    blocked_repository: BlockedUserRepository
    rbac_manager: RBACManagerInterface
    avatar_url_service: ProfileAvatarUrlService
    privacy_service: ProfilePrivacyService

    async def handle(self, query: SearchContactsQuery) -> ContactSearchDTO:
        check_contact_owner(self.rbac_manager, query.owner_id, query.user_jwt_data)

        raw = query.query.strip()
        if not raw:
            return ContactSearchDTO(items=[])

        if raw.startswith("@"):
            result = await self._search_username(query.owner_id, raw[1:])
        elif len(raw) < profile_config.CONTACTS_SEARCH_MIN_PREFIX:
            return ContactSearchDTO(items=[])
        else:
            result = await self._search_own(query.owner_id, raw, query.limit)

        hidden = await self.blocked_repository.blockers_of(
            query.owner_id, [item.user_id for item in result.items]
        )
        for item in result.items:
            if item.user_id in hidden and item.profile is not None:
                item.profile.avatars = {}

        await self.privacy_service.hide_photos(
            query.owner_id, [item.profile for item in result.items]
        )
        await self.avatar_url_service.attach(item.profile for item in result.items)

        return result

    async def _search_username(self, owner_id: int, username: str) -> ContactSearchDTO:
        if not username:
            return ContactSearchDTO(items=[])

        profile = await self.profile_repository.get_by_username(username)
        if profile is None:
            return ContactSearchDTO(items=[])

        contact = await self.contact_repository.get(owner_id, profile.id, with_profile=True)

        return ContactSearchDTO(
            items=[
                ContactSearchItemDTO(
                    user_id=profile.id,
                    profile=ContactProfileDTO.model_validate(profile),
                    contact=UserContactDTO.model_validate(contact) if contact else None,
                )
            ]
        )

    async def _search_own(self, owner_id: int, prefix: str, limit: int) -> ContactSearchDTO:
        page_limit = min(max(limit, 1), profile_config.CONTACTS_SEARCH_LIMIT)
        contacts = await self.contact_repository.search_own(owner_id, prefix, page_limit)

        return ContactSearchDTO(
            items=[
                ContactSearchItemDTO(
                    user_id=contact.contact_id,
                    profile=(
                        ContactProfileDTO.model_validate(contact.profile)
                        if contact.profile is not None
                        else None
                    ),
                    contact=UserContactDTO.model_validate(contact),
                )
                for contact in contacts
            ]
        )
