from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.exceptions import NotFoundUsernameProfileError
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.privacy import ProfilePrivacyService


@dataclass(frozen=True)
class GetProfileByUsernameQuery(BaseQuery):
    username: str
    viewer_id: int | None = None


@dataclass(frozen=True)
class GetProfileByUsernameQueryHandler(BaseQueryHandler[GetProfileByUsernameQuery, ProfileDTO]):
    profile_repository: ProfileRepository
    avatar_url_service: ProfileAvatarUrlService
    privacy_service: ProfilePrivacyService

    async def handle(self, query: GetProfileByUsernameQuery) -> ProfileDTO:
        profile = await self.profile_repository.cache(
            ProfileDTO, self._handle, ttl=60,
            username=query.username
        )

        await self.privacy_service.hide_photos(query.viewer_id, [profile])
        await self.avatar_url_service.attach([profile])

        return profile

    async def _handle(self, username: str) -> ProfileDTO:
        profile = await self.profile_repository.get_by_username(username)
        if profile is None:
            raise NotFoundUsernameProfileError(username=username)

        return ProfileDTO.model_validate(profile)
