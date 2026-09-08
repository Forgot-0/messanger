import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.commands.sessions.deactivate_session import (
    UserDeactivateSessionCommand,
    UserDeactivateSessionCommandHandler,
)
from app.auth.exceptions import NotFoundOrInactiveSessionError
from app.auth.filters.sessions import SessionFilter
from app.auth.models.user import User
from app.auth.queries.sessions.get_list import GetListSessionQuery, GetListSessionQueryHandler
from app.auth.queries.sessions.get_list_by_user import (
    GetListSessionsUserQuery,
    GetListSessionsUserQueryHandler,
)
from app.auth.repositories.session import SessionRepository
from app.core.filters.pagination import Pagination
from app.core.services.auth.exceptions import AccessDeniedError
from tests.auth.integration.factories import SessionFactory
from tests.support.jwt import jwt_from_user


@pytest.fixture
async def deactivate_handler(
    request_container: AsyncContainer,
) -> UserDeactivateSessionCommandHandler:
    return await request_container.get(UserDeactivateSessionCommandHandler)


async def persist_session(db_session: AsyncSession, user_id: int, **kwargs):
    session = SessionFactory.create(user_id=user_id, **kwargs)
    db_session.add(session)
    await db_session.commit()
    return session


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestDeactivateSession:

    async def test_owner_closes_their_own_session(
        self,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        session_repository: SessionRepository,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        session = await persist_session(db_session, standard_user.id)

        await deactivate_handler.handle(
            UserDeactivateSessionCommand(
                session_id=session.id, user_jwt_data=jwt_from_user(standard_user)
            )
        )

        stored = await session_repository.get_by_id(session.id)
        assert stored is not None
        assert stored.is_active is False

    async def test_foreign_session_looks_like_it_does_not_exist(
        self,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        session_repository: SessionRepository,
        db_session: AsyncSession,
        standard_user: User,
        unverified_user: User,
    ) -> None:
        victim_session = await persist_session(db_session, unverified_user.id)

        with pytest.raises(NotFoundOrInactiveSessionError):
            await deactivate_handler.handle(
                UserDeactivateSessionCommand(
                    session_id=victim_session.id,
                    user_jwt_data=jwt_from_user(standard_user),
                )
            )

        untouched = await session_repository.get_by_id(victim_session.id)
        assert untouched is not None
        assert untouched.is_active is True

    async def test_admin_can_close_a_foreign_session(
        self,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        session_repository: SessionRepository,
        db_session: AsyncSession,
        admin_user: User,
        standard_user: User,
    ) -> None:
        session = await persist_session(db_session, standard_user.id)

        await deactivate_handler.handle(
            UserDeactivateSessionCommand(
                session_id=session.id, user_jwt_data=jwt_from_user(admin_user)
            )
        )

        stored = await session_repository.get_by_id(session.id)
        assert stored is not None
        assert stored.is_active is False

    async def test_missing_session_is_reported(
        self,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        standard_user: User,
    ) -> None:
        with pytest.raises(NotFoundOrInactiveSessionError):
            await deactivate_handler.handle(
                UserDeactivateSessionCommand(
                    session_id=999_999, user_jwt_data=jwt_from_user(standard_user)
                )
            )

    async def test_closing_twice_is_idempotent(
        self,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        session_repository: SessionRepository,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        session = await persist_session(db_session, standard_user.id)
        command = UserDeactivateSessionCommand(
            session_id=session.id, user_jwt_data=jwt_from_user(standard_user)
        )

        await deactivate_handler.handle(command)
        await deactivate_handler.handle(command)

        stored = await session_repository.get_by_id(session.id)
        assert stored is not None
        assert stored.is_active is False

    async def test_closed_session_leaves_the_active_list(
        self,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        session_repository: SessionRepository,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        session = await persist_session(db_session, standard_user.id)

        await deactivate_handler.handle(
            UserDeactivateSessionCommand(
                session_id=session.id, user_jwt_data=jwt_from_user(standard_user)
            )
        )

        active = await session_repository.get_active_by_user(standard_user.id)
        assert session.id not in [s.id for s in active]


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestSessionQueries:

    @pytest.fixture
    async def my_sessions_handler(
        self, request_container: AsyncContainer
    ) -> GetListSessionsUserQueryHandler:
        return await request_container.get(GetListSessionsUserQueryHandler)

    @pytest.fixture
    async def all_sessions_handler(
        self, request_container: AsyncContainer
    ) -> GetListSessionQueryHandler:
        return await request_container.get(GetListSessionQueryHandler)

    async def test_own_list_shows_only_my_active_sessions(
        self,
        my_sessions_handler: GetListSessionsUserQueryHandler,
        db_session: AsyncSession,
        standard_user: User,
        unverified_user: User,
    ) -> None:
        mine = await persist_session(db_session, standard_user.id)
        await persist_session(db_session, unverified_user.id)

        result = await my_sessions_handler.handle(
            GetListSessionsUserQuery(user_jwt_data=jwt_from_user(standard_user))
        )

        assert [s.id for s in result] == [mine.id]

    async def test_own_list_hides_closed_sessions(
        self,
        my_sessions_handler: GetListSessionsUserQueryHandler,
        deactivate_handler: UserDeactivateSessionCommandHandler,
        db_session: AsyncSession,
        standard_user: User,
    ) -> None:
        alive = await persist_session(db_session, standard_user.id)
        closed = await persist_session(db_session, standard_user.id, device_id="other-device")

        await deactivate_handler.handle(
            UserDeactivateSessionCommand(
                session_id=closed.id, user_jwt_data=jwt_from_user(standard_user)
            )
        )

        result = await my_sessions_handler.handle(
            GetListSessionsUserQuery(user_jwt_data=jwt_from_user(standard_user))
        )

        assert [s.id for s in result] == [alive.id]

    async def test_user_without_sessions_gets_an_empty_list(
        self,
        my_sessions_handler: GetListSessionsUserQueryHandler,
        unverified_user: User,
    ) -> None:
        result = await my_sessions_handler.handle(
            GetListSessionsUserQuery(user_jwt_data=jwt_from_user(unverified_user))
        )

        assert result == []

    async def test_admin_list_requires_the_view_permission(
        self,
        all_sessions_handler: GetListSessionQueryHandler,
        standard_user: User,
    ) -> None:
        session_filter = SessionFilter()
        session_filter.set_pagination(Pagination(page=1, page_size=20))

        with pytest.raises(AccessDeniedError):
            await all_sessions_handler.handle(
                GetListSessionQuery(
                    session_filter=session_filter,
                    user_jwt_data=jwt_from_user(standard_user),
                )
            )

    async def test_admin_sees_sessions_of_every_user(
        self,
        all_sessions_handler: GetListSessionQueryHandler,
        db_session: AsyncSession,
        admin_user: User,
        standard_user: User,
        unverified_user: User,
    ) -> None:
        await persist_session(db_session, standard_user.id)
        await persist_session(db_session, unverified_user.id)

        session_filter = SessionFilter()
        session_filter.set_pagination(Pagination(page=1, page_size=20))

        result = await all_sessions_handler.handle(
            GetListSessionQuery(
                session_filter=session_filter, user_jwt_data=jwt_from_user(admin_user)
            )
        )

        assert result.total >= 2

    async def test_admin_list_is_paginated(
        self,
        all_sessions_handler: GetListSessionQueryHandler,
        db_session: AsyncSession,
        admin_user: User,
        standard_user: User,
    ) -> None:
        for i in range(3):
            await persist_session(db_session, standard_user.id, device_id=f"device-{i}")

        session_filter = SessionFilter()
        session_filter.set_pagination(Pagination(page=1, page_size=2))

        result = await all_sessions_handler.handle(
            GetListSessionQuery(
                session_filter=session_filter, user_jwt_data=jwt_from_user(admin_user)
            )
        )

        assert len(result.items) == 2
        assert result.page_size == 2
        assert result.total >= 3
