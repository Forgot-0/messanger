from dataclasses import dataclass

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import selectinload

from app.auth.filters.users import UserFilter
from app.auth.models.permission import Permission
from app.auth.models.role import Role
from app.auth.models.user import User
from app.core.db.repository import CacheRepository, IRepository


@dataclass
class UserRepository(IRepository[User], CacheRepository):
    _LIST_VERSION_KEY = "user:list"

    async def get_by_email(self, email: str) -> (User | None):
        result = await self.session.execute(User.select_not_deleted().where(User.email == email))
        return result.scalar()

    async def get_with_roles_by_email(self, email: str) -> (User | None):
        result = await self.session.execute(
            User.select_not_deleted().options(
                selectinload(User.permissions), selectinload(User.roles).selectinload(Role.permissions)
            ).where(User.email == email)
        )
        return result.scalar()

    async def get_by_username(self, username: str) -> (User | None):
        result = await self.session.execute(User.select_not_deleted().where(User.username == username))
        return result.scalar()

    async def get_with_roles_by_username(self, username: str) -> (User | None):
        result = await self.session.execute(
            User.select_not_deleted().options(
                selectinload(User.permissions), selectinload(User.roles).selectinload(Role.permissions)
            ).where(User.username == username)
        )
        return result.scalar()

    async def is_username_taken(self, username: str, exclude_user_id: int | None = None) -> bool:
        condition = func.lower(User.username) == func.lower(username)
        if exclude_user_id is not None:
            condition = condition & (User.id != exclude_user_id)

        result = await self.session.execute(select(exists().where(condition)))
        return bool(result.scalar())

    async def get_by_id(self, user_id: int) -> (User | None):
        result = await self.session.execute(User.select_not_deleted().where(User.id == user_id))
        return result.scalars().first()

    async def get_user_with_roles_by_id(self, user_id: int) -> User | None:
        query = User.select_not_deleted().options(selectinload(User.roles)).where(User.id == user_id)
        results = await self.session.execute(query)
        return results.scalar()

    async def get_user_with_permission_by_id(self, user_id: int) -> User | None:
        query = User.select_not_deleted().options(
           selectinload(User.permissions), selectinload(User.roles).selectinload(Role.permissions)
        ).where(User.id == user_id)
        results = await self.session.execute(query)
        return results.scalar()

    async def create(self, user: User) -> None:
        self.session.add(user)

    def apply_relationship_filters(self, stmt: Select, _filters: UserFilter) -> Select:

        if _filters.role_names:
            stmt = stmt.join(User.roles).where(User.roles.contains(_filters.role_names))

        if _filters.permission_names:
            stmt = stmt.join(User.permissions).where(Permission.name.in_(_filters.permission_names))

        return stmt
