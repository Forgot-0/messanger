from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.db.repository import CacheRepository, IRepository
from app.profiles.models.profile import Profile


@dataclass
class ProfileRepository(IRepository[Profile], CacheRepository):
    _LIST_VERSION_KEY = "profile:list"

    async def create(self, profile: Profile) -> None:
        self.session.add(profile)

    async def get_by_id(self, profile_id: int) -> Profile | None:
        query = select(Profile).where(Profile.id==profile_id).options(selectinload(Profile.links))
        result = await self.session.execute(query)
        return result.scalar()

    async def get_by_username(self, username: str) -> Profile | None:
        query = select(Profile).where(
            func.lower(Profile.username) == username.lower(),
            Profile.deleted_at.is_(None),
        )
        result = await self.session.execute(query)
        return result.scalar()

    async def get_by_ids(self, profile_ids: list[int]) -> dict[int, Profile]:
        if not profile_ids:
            return {}

        query = select(Profile).where(
            Profile.id.in_(profile_ids), Profile.deleted_at.is_(None)
        )
        result = await self.session.execute(query)
        return {profile.id: profile for profile in result.scalars().all()}
