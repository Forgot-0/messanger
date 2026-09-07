from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.repositories.profiles import ProfileRepository


@dataclass(frozen=True)
class GetProfileByIdQuery(BaseQuery):
    profile_id: int
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class GetProfileByIdQueryHandler(BaseQueryHandler[GetProfileByIdQuery, ProfileDTO]):
    profile_repository: ProfileRepository

    async def handle(self, query: GetProfileByIdQuery) -> ProfileDTO:
        return await self.profile_repository.cache(
            ProfileDTO, self._handle, ttl=60,
            query=query
        )

    async def _handle(self, query: GetProfileByIdQuery) -> ProfileDTO:
        profile = await self.profile_repository.get_by_id(query.profile_id)
        if profile is None:
            raise NotFoundProfileError(profile_id=query.profile_id)

        return ProfileDTO.model_validate(profile)
