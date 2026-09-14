from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.db.convertor import SQLAlchemyFilterConverter
from app.core.db.repository import CacheRepository, IRepository, PageResult
from app.profiles.filters.profiles import ProfileFilter
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

    async def search(
        self,
        filters: ProfileFilter,
        query: str | None = None,
        exclude_ids: Collection[int] = (),
    ) -> PageResult[Profile]:
        stmt = Profile.select_not_deleted()

        loading_options = SQLAlchemyFilterConverter.build_loading_options(
            Profile, filters.loading_config
        )
        if loading_options:
            stmt = stmt.options(*loading_options)

        conditions = SQLAlchemyFilterConverter.filter_to_sqlalchemy_conditions(Profile, filters)

        if query:
            conditions.append(
                or_(
                    Profile.username.icontains(query, autoescape=True),
                    Profile.display_name.icontains(query, autoescape=True),
                )
            )

        if exclude_ids:
            conditions.append(Profile.id.not_in(exclude_ids))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_clauses = SQLAlchemyFilterConverter.get_sort_attributes(Profile, filters.sort_fields)
        stmt = stmt.order_by(*sort_clauses) if sort_clauses else stmt.order_by(Profile.id)

        stmt = stmt.offset(filters.pagination.offset).limit(filters.pagination.limit)
        result = await self.session.execute(stmt)

        return PageResult(
            items=list(result.scalars().all()),
            total=total,
            page=filters.pagination.page,
            page_size=filters.pagination.page_size,
        )

    async def get_by_ids(self, profile_ids: list[int]) -> dict[int, Profile]:
        if not profile_ids:
            return {}

        query = select(Profile).where(
            Profile.id.in_(profile_ids), Profile.deleted_at.is_(None)
        )
        result = await self.session.execute(query)
        return {profile.id: profile for profile in result.scalars().all()}
