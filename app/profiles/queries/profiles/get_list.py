from dataclasses import dataclass

from app.core.db.repository import PageResult
from app.core.queries import BaseQuery, BaseQueryHandler
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.filters.profiles import ProfileFilter
from app.profiles.repositories.contacts import BlockedUserRepository
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.privacy import ProfilePrivacyService


@dataclass(frozen=True)
class GetProfilesQuery(BaseQuery):
    profile_filter: ProfileFilter
    viewer_id: int
    query: str | None = None


@dataclass(frozen=True)
class GetProfilesQueryHandler(BaseQueryHandler[GetProfilesQuery, PageResult[ProfileDTO]]):
    profile_repository: ProfileRepository
    blocked_repository: BlockedUserRepository
    avatar_url_service: ProfileAvatarUrlService
    privacy_service: ProfilePrivacyService

    async def handle(self, query: GetProfilesQuery) -> PageResult[ProfileDTO]:
        if query.query is not None:
            page = await self._handle(query)
        else:
            page = await self.profile_repository.cache_paginated(
                ProfileDTO, self._handle, ttl=360,
                query=query
            )

        hidden = await self.blocked_repository.blockers_of(
            query.viewer_id, [profile.id for profile in page.items]
        )
        for profile in page.items:
            if profile.id in hidden:
                profile.avatars = {}

        await self.privacy_service.hide_photos(query.viewer_id, page.items)
        await self.avatar_url_service.attach(page.items)

        return page

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
