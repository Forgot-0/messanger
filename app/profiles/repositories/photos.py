from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select

from app.core.db.repository import IRepository, PageResult
from app.profiles.filters.photos import ProfilePhotoFilter
from app.profiles.models.photo import ProfilePhoto


@dataclass
class ProfilePhotoRepository(IRepository[ProfilePhoto]):

    async def create(self, photo: ProfilePhoto) -> None:
        self.session.add(photo)

    async def get_own(self, photo_id: UUID, user_id: int) -> ProfilePhoto | None:
        query = select(ProfilePhoto).where(
            ProfilePhoto.id == photo_id,
            ProfilePhoto.user_id == user_id,
        )
        result = await self.session.execute(query)
        return result.scalar()

    async def get_latest(self, user_id: int) -> ProfilePhoto | None:
        query = (
            select(ProfilePhoto)
            .where(ProfilePhoto.user_id == user_id)
            .order_by(ProfilePhoto.set_main_at.desc(), ProfilePhoto.id.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar()

    async def count(self, user_id: int) -> int:
        query = select(func.count()).select_from(ProfilePhoto).where(ProfilePhoto.user_id == user_id)
        result = await self.session.execute(query)
        return int(result.scalar_one())

    async def delete(self, photo: ProfilePhoto) -> None:
        await self.session.delete(photo)

    async def get_page(self, filters: ProfilePhotoFilter) -> PageResult[ProfilePhoto]:
        return await self.find_by_filter(ProfilePhoto, filters)
