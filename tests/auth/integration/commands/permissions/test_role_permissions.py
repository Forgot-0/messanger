import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.commands.permissions.remove_permission_user import (
    DeletePermissionToUserCommand,
    DeletePermissionToUserCommandHandler,
)
from app.auth.commands.roles.add_permissions import (
    AddPermissionRoleCommand,
    AddPermissionRoleCommandHandler,
)
from app.auth.commands.roles.delete_permissions import (
    DeletePermissionRoleCommand,
    DeletePermissionRoleCommandHandler,
)
from app.auth.commands.roles.update import RoleUpdateCommand, RoleUpdateCommandHandler
from app.auth.exceptions import (
    InvalidRoleNameError,
    NotFoundPermissionsError,
    NotFoundRoleError,
    NotFoundUserError,
)
from app.auth.models.permission import Permission
from app.auth.models.user import User
from app.auth.repositories.role import RoleRepository
from app.auth.repositories.session import TokenBlacklistRepository
from app.auth.repositories.user import UserRepository
from app.core.services.auth.exceptions import AccessDeniedError
from tests.auth.integration.factories import RoleFactory, UserFactory
from tests.support.jwt import jwt_from_user


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestDeletePermissionFromUser:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> DeletePermissionToUserCommandHandler:
        return await request_container.get(DeletePermissionToUserCommandHandler)

    async def _user_with_permission(
        self, db_session: AsyncSession, name: str, *, email: str, username: str
    ) -> tuple[User, Permission]:
        permission = Permission(name=name)
        db_session.add(permission)
        await db_session.flush()

        user = UserFactory.create_verified(
            email=email, username=username, permissions={permission}
        )
        db_session.add(user)
        await db_session.commit()
        return user, permission

    async def test_permission_is_removed_from_the_user(
        self,
        handler: DeletePermissionToUserCommandHandler,
        user_repository: UserRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        target, _ = await self._user_with_permission(
            db_session, "post:publish", email="perm@example.com", username="permuser"
        )

        await handler.handle(
            DeletePermissionToUserCommand(
                user_jwt_data=jwt_from_user(admin_user),
                user_id=target.id,
                permissions={"post:publish"},
            )
        )

        updated = await user_repository.get_user_with_permission_by_id(target.id)
        assert updated is not None
        assert "post:publish" not in {p.name for p in updated.permissions}

    async def test_users_tokens_are_blacklisted_after_the_revoke(
        self,
        handler: DeletePermissionToUserCommandHandler,
        token_blacklist_repository: TokenBlacklistRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        target, _ = await self._user_with_permission(
            db_session, "post:edit", email="revoke@example.com", username="revokeuser"
        )

        await handler.handle(
            DeletePermissionToUserCommand(
                user_jwt_data=jwt_from_user(admin_user),
                user_id=target.id,
                permissions={"post:edit"},
            )
        )

        assert await token_blacklist_repository.get_user_backlist(target.id) is not None

    async def test_unknown_permission_name_is_reported(
        self,
        handler: DeletePermissionToUserCommandHandler,
        admin_user: User,
        standard_user: User,
    ) -> None:
        with pytest.raises(NotFoundPermissionsError) as exc_info:
            await handler.handle(
                DeletePermissionToUserCommand(
                    user_jwt_data=jwt_from_user(admin_user),
                    user_id=standard_user.id,
                    permissions={"never:existed"},
                )
            )

        assert exc_info.value.missing == {"never:existed"}

    async def test_unknown_user_is_reported(
        self,
        handler: DeletePermissionToUserCommandHandler,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        db_session.add(Permission(name="some:perm"))
        await db_session.commit()

        with pytest.raises(NotFoundUserError):
            await handler.handle(
                DeletePermissionToUserCommand(
                    user_jwt_data=jwt_from_user(admin_user),
                    user_id=999_999,
                    permissions={"some:perm"},
                )
            )

    async def test_regular_user_cannot_revoke(
        self,
        handler: DeletePermissionToUserCommandHandler,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        db_session.add(Permission(name="other:perm"))
        await db_session.commit()

        with pytest.raises(AccessDeniedError):
            await handler.handle(
                DeletePermissionToUserCommand(
                    user_jwt_data=jwt_from_user(standard_user),
                    user_id=standard_user.id,
                    permissions={"other:perm"},
                )
            )

    async def test_revoking_a_permission_the_user_never_had(
        self,
        handler: DeletePermissionToUserCommandHandler,
        db_session: AsyncSession,
        admin_user: User,
        standard_user: User,
    ) -> None:
        db_session.add(Permission(name="unheld:perm"))
        await db_session.commit()

        with pytest.raises(NotFoundPermissionsError) as exc_info:
            await handler.handle(
                DeletePermissionToUserCommand(
                    user_jwt_data=jwt_from_user(admin_user),
                    user_id=standard_user.id,
                    permissions={"unheld:perm"},
                )
            )

        assert exc_info.value.missing == {"unheld:perm"}


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestRolePermissions:

    @pytest.fixture
    async def add_handler(
        self, request_container: AsyncContainer
    ) -> AddPermissionRoleCommandHandler:
        return await request_container.get(AddPermissionRoleCommandHandler)

    @pytest.fixture
    async def delete_handler(
        self, request_container: AsyncContainer
    ) -> DeletePermissionRoleCommandHandler:
        return await request_container.get(DeletePermissionRoleCommandHandler)

    async def _role_with(
        self, db_session: AsyncSession, name: str, *permission_names: str
    ) -> None:
        permissions = [Permission(name=n) for n in permission_names]
        db_session.add_all(permissions)
        await db_session.flush()

        role = RoleFactory.create(name=name, security_level=3)
        role.permissions = set(permissions)
        db_session.add(role)
        await db_session.commit()

    async def test_permission_is_added_to_the_role(
        self,
        add_handler: AddPermissionRoleCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        await self._role_with(db_session, "editor_role")
        db_session.add(Permission(name="article:write"))
        await db_session.commit()

        await add_handler.handle(
            AddPermissionRoleCommand(
                role_name="editor_role",
                permissions={"article:write"},
                user_jwt_data=jwt_from_user(admin_user),
            )
        )

        role = await role_repository.get_with_permission_by_name("editor_role")
        assert role is not None
        assert "article:write" in {p.name for p in role.permissions}

    async def test_permission_is_removed_from_the_role(
        self,
        delete_handler: DeletePermissionRoleCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        await self._role_with(db_session, "trimmed_role", "article:write", "article:read")

        await delete_handler.handle(
            DeletePermissionRoleCommand(
                role_name="trimmed_role",
                permissions={"article:write"},
                user_jwt_data=jwt_from_user(admin_user),
            )
        )

        role = await role_repository.get_with_permission_by_name("trimmed_role")
        assert role is not None
        assert {p.name for p in role.permissions} == {"article:read"}

    async def test_adding_several_permissions_at_once(
        self,
        add_handler: AddPermissionRoleCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        await self._role_with(db_session, "multi_role")
        db_session.add_all([Permission(name="a:one"), Permission(name="a:two")])
        await db_session.commit()

        await add_handler.handle(
            AddPermissionRoleCommand(
                role_name="multi_role",
                permissions={"a:one", "a:two"},
                user_jwt_data=jwt_from_user(admin_user),
            )
        )

        role = await role_repository.get_with_permission_by_name("multi_role")
        assert role is not None
        assert {"a:one", "a:two"} <= {p.name for p in role.permissions}

    async def test_partially_unknown_permission_set_is_rejected_entirely(
        self,
        add_handler: AddPermissionRoleCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        await self._role_with(db_session, "partial_role")
        db_session.add(Permission(name="known:perm"))
        await db_session.commit()

        with pytest.raises(NotFoundPermissionsError) as exc_info:
            await add_handler.handle(
                AddPermissionRoleCommand(
                    role_name="partial_role",
                    permissions={"known:perm", "unknown:perm"},
                    user_jwt_data=jwt_from_user(admin_user),
                )
            )

        assert exc_info.value.missing == {"unknown:perm"}

        role = await role_repository.get_with_permission_by_name("partial_role")
        assert role is not None
        assert role.permissions == set()

    async def test_unknown_role_is_reported(
        self,
        add_handler: AddPermissionRoleCommandHandler,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        db_session.add(Permission(name="lonely:perm"))
        await db_session.commit()

        with pytest.raises(NotFoundRoleError):
            await add_handler.handle(
                AddPermissionRoleCommand(
                    role_name="no_such_role",
                    permissions={"lonely:perm"},
                    user_jwt_data=jwt_from_user(admin_user),
                )
            )

    async def test_regular_user_cannot_change_role_permissions(
        self,
        add_handler: AddPermissionRoleCommandHandler,
        delete_handler: DeletePermissionRoleCommandHandler,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        await self._role_with(db_session, "guarded_role", "guard:perm")
        jwt = jwt_from_user(standard_user)

        with pytest.raises(AccessDeniedError):
            await add_handler.handle(
                AddPermissionRoleCommand(
                    role_name="guarded_role", permissions={"guard:perm"}, user_jwt_data=jwt
                )
            )

        with pytest.raises(AccessDeniedError):
            await delete_handler.handle(
                DeletePermissionRoleCommand(
                    role_name="guarded_role", permissions={"guard:perm"}, user_jwt_data=jwt
                )
            )

    async def test_role_above_the_callers_level_is_protected(
        self,
        add_handler: AddPermissionRoleCommandHandler,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        role = RoleFactory.create(name="high_role", security_level=10)
        db_session.add(role)
        db_session.add(Permission(name="high:perm"))
        await db_session.commit()

        with pytest.raises(AccessDeniedError):
            await add_handler.handle(
                AddPermissionRoleCommand(
                    role_name="high_role",
                    permissions={"high:perm"},
                    user_jwt_data=jwt_from_user(standard_user),
                )
            )


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestRoleUpdate:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> RoleUpdateCommandHandler:
        return await request_container.get(RoleUpdateCommandHandler)

    async def _role(self, db_session: AsyncSession, **kwargs) -> int:
        role = RoleFactory.create(**kwargs)
        db_session.add(role)
        await db_session.commit()
        return role.id

    async def test_description_and_level_are_updated(
        self,
        handler: RoleUpdateCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        role_id = await self._role(
            db_session, name="updatable", security_level=3, description="старое"
        )

        await handler.handle(
            RoleUpdateCommand(
                id=role_id,
                name=None,
                description="новое описание",
                security_level=5,
                user_jwt_data=jwt_from_user(admin_user),
            )
        )

        role = await role_repository.get_by_name("updatable")
        assert role is not None
        assert role.description == "новое описание"
        assert role.security_level == 5

    async def test_missing_fields_leave_the_role_alone(
        self,
        handler: RoleUpdateCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        role_id = await self._role(
            db_session, name="untouched", security_level=4, description="как было"
        )

        await handler.handle(
            RoleUpdateCommand(
                id=role_id,
                name=None,
                description=None,
                security_level=None,
                user_jwt_data=jwt_from_user(admin_user),
            )
        )

        role = await role_repository.get_by_name("untouched")
        assert role is not None
        assert role.description == "как было"
        assert role.security_level == 4

    async def test_unknown_role_is_reported(
        self,
        handler: RoleUpdateCommandHandler,
        admin_user: User,
    ) -> None:
        with pytest.raises(NotFoundRoleError):
            await handler.handle(
                RoleUpdateCommand(
                    id=999_999,
                    name=None,
                    description="x",
                    security_level=None,
                    user_jwt_data=jwt_from_user(admin_user),
                )
            )

    async def test_raising_the_level_above_your_own_is_denied(
        self,
        handler: RoleUpdateCommandHandler,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        role_id = await self._role(db_session, name="climber", security_level=2)

        with pytest.raises(AccessDeniedError):
            await handler.handle(
                RoleUpdateCommand(
                    id=role_id,
                    name=None,
                    description=None,
                    security_level=10,
                    user_jwt_data=jwt_from_user(admin_user),
                )
            )

    async def test_regular_user_cannot_update_a_role(
        self,
        handler: RoleUpdateCommandHandler,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        role_id = await self._role(db_session, name="protected", security_level=2)

        with pytest.raises(AccessDeniedError):
            await handler.handle(
                RoleUpdateCommand(
                    id=role_id,
                    name=None,
                    description="взлом",
                    security_level=None,
                    user_jwt_data=jwt_from_user(standard_user),
                )
            )

    async def test_rename_goes_through_the_same_validation_as_creation(
        self,
        handler: RoleUpdateCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        role_id = await self._role(db_session, name="renamable", security_level=3)

        with pytest.raises(InvalidRoleNameError):
            await handler.handle(
                RoleUpdateCommand(
                    id=role_id,
                    name="ab",
                    description=None,
                    security_level=None,
                    user_jwt_data=jwt_from_user(admin_user),
                )
            )

        assert await role_repository.get_by_name("renamable") is not None

    async def test_valid_rename_is_applied(
        self,
        handler: RoleUpdateCommandHandler,
        role_repository: RoleRepository,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        role_id = await self._role(db_session, name="old_name", security_level=3)

        await handler.handle(
            RoleUpdateCommand(
                id=role_id,
                name="new_name",
                description=None,
                security_level=None,
                user_jwt_data=jwt_from_user(admin_user),
            )
        )

        assert await role_repository.get_by_name("new_name") is not None
        assert await role_repository.get_by_name("old_name") is None

    async def test_regular_user_cannot_claim_a_system_prefix(
        self,
        handler: RoleUpdateCommandHandler,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        role_id = await self._role(db_session, name="ordinary", security_level=2)

        with pytest.raises(AccessDeniedError):
            await handler.handle(
                RoleUpdateCommand(
                    id=role_id,
                    name="system_sneaky",
                    description=None,
                    security_level=None,
                    user_jwt_data=jwt_from_user(standard_user),
                )
            )
