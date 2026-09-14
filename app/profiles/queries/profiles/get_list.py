from dataclasses import dataclass

from app.core.db.repository import PageResult
from app.core.queries import BaseQuery, BaseQueryHandler
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.filters.profiles import ProfileFilter
from app.profiles.repositories.contacts import BlockedUserRepository
from app.profiles.repositories.profiles import ProfileRepository


@dataclass(frozen=True)
class GetProfilesQuery(BaseQuery):
    profile_filter: ProfileFilter
    viewer_id: int
    query: str | None = None


@dataclass(frozen=True)
class GetProfilesQueryHandler(BaseQueryHandler[GetProfilesQuery, PageResult[ProfileDTO]]):
    profile_repository: ProfileRepository
    blocked_repository: BlockedUserRepository

    async def handle(self, query: GetProfilesQuery) -> PageResult[ProfileDTO]:
        if query.query is not None:
            return await self._handle(query)

        return await self.profile_repository.cache_paginated(
            ProfileDTO, self._handle, ttl=360,
            query=query
        )

    async def _handle(self, query: GetProfilesQuery) -> PageResult[ProfileDTO]:
        blocked = await self.blocked_repository.get_block_list(query.viewer_id)

        profiles = await self.profile_repository.search(
            query.profile_filter, query=query.query, exclude_ids=blocked
        )

        return PageResult(
            items=[ProfileDTO.model_validate(profile) for profile in profiles.items],
            total=profiles.total,
            page=profiles.page,
            page_size=profiles.page_size
        )
