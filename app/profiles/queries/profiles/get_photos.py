from dataclasses import dataclass

from app.core.db.repository import PageResult
from app.privacy.utils import PrivacyRule
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.profiles.dtos.profiles import ProfilePhotoDTO
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.filters.photos import ProfilePhotoFilter
from app.profiles.repositories.contacts import BlockedUserRepository
from app.profiles.repositories.photos import ProfilePhotoRepository
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from app.profiles.services.privacy import ProfilePrivacyService


@dataclass(frozen=True)
class GetProfilePhotosQuery(BaseQuery):
    profile_id: int
    photo_filter: ProfilePhotoFilter
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class GetProfilePhotosQueryHandler(BaseQueryHandler[GetProfilePhotosQuery, PageResult[ProfilePhotoDTO]]):
    profile_repository: ProfileRepository
    photo_repository: ProfilePhotoRepository
    blocked_repository: BlockedUserRepository
    privacy_service: ProfilePrivacyService
    avatar_url_service: ProfileAvatarUrlService

    async def handle(self, query: GetProfilePhotosQuery) -> PageResult[ProfilePhotoDTO]:
        profile = await self.profile_repository.get_active_by_id(query.profile_id)
        if profile is None:
            raise NotFoundProfileError(profile_id=query.profile_id)

        pagination = query.photo_filter.pagination
        hidden: PageResult[ProfilePhotoDTO] = PageResult(
            items=[], total=0, page=pagination.page, page_size=pagination.page_size
        )

        viewer_id = int(query.user_jwt_data.id)
        if viewer_id != profile.id:
            if viewer_id in await self.blocked_repository.get_block_list(profile.id):
                return hidden

            allowed = await self.privacy_service.allowed_by(PrivacyRule.PHOTO, viewer_id, [profile.id])
            if profile.id not in allowed:
                return hidden

        page = await self.photo_repository.get_page(query.photo_filter)
        items = [ProfilePhotoDTO.model_validate(photo) for photo in page.items]
        for item in items:
            item.is_main = item.id == profile.photo_id

        await self.avatar_url_service.attach(items)

        return PageResult(
            items=items, total=page.total, page=page.page, page_size=page.page_size
        )
