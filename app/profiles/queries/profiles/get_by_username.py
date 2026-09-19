from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.exceptions import NotFoundUsernameProfileError
from app.profiles.repositories.profiles import ProfileRepository


@dataclass(frozen=True)
class GetProfileByUsernameQuery(BaseQuery):
    username: str


@dataclass(frozen=True)
class GetProfileByUsernameQueryHandler(BaseQueryHandler[GetProfileByUsernameQuery, ProfileDTO]):
    profile_repository: ProfileRepository

    async def handle(self, query: GetProfileByUsernameQuery) -> ProfileDTO:
        return await self.profile_repository.cache(
            ProfileDTO, self._handle, ttl=60,
            query=query
        )

    async def _handle(self, query: GetProfileByUsernameQuery) -> ProfileDTO:
        profile = await self.profile_repository.get_by_username(query.username)
        if profile is None:
            raise NotFoundUsernameProfileError(username=query.username)

        return ProfileDTO.model_validate(profile)
