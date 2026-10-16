from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.repositories.contacts import BlockedUserRepository
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.privacy import ProfilePrivacyService


@dataclass(frozen=True)
class GetProfileByIdQuery(BaseQuery):
    profile_id: int
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class GetProfileByIdQueryHandler(BaseQueryHandler[GetProfileByIdQuery, ProfileDTO]):
    profile_repository: ProfileRepository
    blocked_repository: BlockedUserRepository
    avatar_url_service: ProfileAvatarUrlService
    privacy_service: ProfilePrivacyService

    async def handle(self, query: GetProfileByIdQuery) -> ProfileDTO:
        profile = await self.profile_repository.cache(
            ProfileDTO, self._handle, ttl=60,
            profile_id=query.profile_id
        )

        viewer_id = int(query.user_jwt_data.id)
        if viewer_id != profile.id and viewer_id in await self.blocked_repository.get_block_list(profile.id):
            profile.avatars = {}

        await self.privacy_service.hide_photos(viewer_id, [profile])
        await self.avatar_url_service.attach([profile])

        return profile

    async def _handle(self, profile_id: int) -> ProfileDTO:
        profile = await self.profile_repository.get_by_id(profile_id)
        if profile is None:
            raise NotFoundProfileError(profile_id=profile_id)

        return ProfileDTO.model_validate(profile)
