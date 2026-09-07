from dataclasses import dataclass

from app.core.db.repository import PageResult
from app.core.queries import BaseQuery, BaseQueryHandler
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.filters.profiles import ProfileFilter
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository


@dataclass(frozen=True)
class GetProfilesQuery(BaseQuery):
    profile_filter: ProfileFilter


@dataclass(frozen=True)
class GetProfilesQueryHandler(BaseQueryHandler[GetProfilesQuery, PageResult[ProfileDTO]]):
    profile_repository: ProfileRepository

    async def handle(self, query: GetProfilesQuery) -> PageResult[ProfileDTO]:
        return await self.profile_repository.cache_paginated(
            ProfileDTO, self._handle, ttl=360,
            query=query
        )

    async def _handle(self, query: GetProfilesQuery) -> PageResult[ProfileDTO]:
        profiles = await self.profile_repository.find_by_filter(
            Profile, query.profile_filter
        )

        return PageResult(
            items=[ProfileDTO.model_validate(profile) for profile in profiles.items],
            total=profiles.total,
            page=profiles.page,
            page_size=profiles.page_size
        )
