from datetime import timedelta

import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from app.profiles.queries.contacts.get_blocked import (
    GetBlockedUsersQuery,
    GetBlockedUsersQueryHandler,
)
from app.profiles.queries.contacts.get_list import GetContactsQuery, GetContactsQueryHandler
from app.profiles.queries.contacts.search import SearchContactsQuery, SearchContactsQueryHandler

OWNER_ID = 1


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestGetContactsQuery:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> GetContactsQueryHandler:
        return await request_container.get(GetContactsQueryHandler)

    async def test_contact_is_returned_with_its_profile(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_profile,
        make_contact,
    ) -> None:
        await make_profile(9201, "friend", "Friend")
        await make_contact(OWNER_ID, 9201, first_name="Вася")

        result = await handler.handle(
            GetContactsQuery(owner_id=OWNER_ID, user_jwt_data=user_jwt)
        )

        assert result.has_next is False
        assert len(result.contacts) == 1
        assert result.contacts[0].first_name == "Вася"
        assert result.contacts[0].profile is not None
        assert result.contacts[0].profile.id == 9201
        assert result.contacts[0].profile.display_name == "Friend"

    async def test_contact_without_profile_is_still_listed(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        await make_contact(OWNER_ID, 9202)

        result = await handler.handle(
            GetContactsQuery(owner_id=OWNER_ID, user_jwt_data=user_jwt)
        )

        assert len(result.contacts) == 1
        assert result.contacts[0].profile is None

    async def test_cursor_walks_the_whole_list_without_repeats(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        for contact_id in (9301, 9302, 9303):
            await make_contact(OWNER_ID, contact_id)

        first = await handler.handle(
            GetContactsQuery(owner_id=OWNER_ID, limit=2, user_jwt_data=user_jwt)
        )
        second = await handler.handle(
            GetContactsQuery(
                owner_id=OWNER_ID,
                limit=2,
                after_contact_id=first.next_contact_id,
                user_jwt_data=user_jwt,
            )
        )

        assert first.has_next is True
        assert first.next_contact_id == 9302
        assert [c.contact_id for c in first.contacts] == [9301, 9302]
        assert [c.contact_id for c in second.contacts] == [9303]
        assert second.has_next is False

    async def test_version_comes_only_with_the_last_page(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        for contact_id in (9401, 9402):
            await make_contact(OWNER_ID, contact_id)

        page = await handler.handle(
            GetContactsQuery(owner_id=OWNER_ID, limit=1, user_jwt_data=user_jwt)
        )
        last = await handler.handle(
            GetContactsQuery(
                owner_id=OWNER_ID,
                limit=1,
                after_contact_id=page.next_contact_id,
                user_jwt_data=user_jwt,
            )
        )

        assert page.version is None
        assert last.version is not None

    async def test_delta_sync_returns_only_fresh_rows(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        now = now_utc()
        await make_contact(OWNER_ID, 9501, updated_at=now - timedelta(hours=2))
        await make_contact(OWNER_ID, 9502, updated_at=now)

        delta = await handler.handle(
            GetContactsQuery(
                owner_id=OWNER_ID,
                updated_after=now - timedelta(hours=1),
                user_jwt_data=user_jwt,
            )
        )

        assert [c.contact_id for c in delta.contacts] == [9502]

    async def test_version_matches_the_freshest_row(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        now = now_utc()
        await make_contact(OWNER_ID, 9511, updated_at=now - timedelta(hours=2))
        await make_contact(OWNER_ID, 9512, updated_at=now)

        result = await handler.handle(
            GetContactsQuery(owner_id=OWNER_ID, user_jwt_data=user_jwt)
        )

        assert result.version == now

    async def test_foreign_contacts_are_not_visible(
        self,
        handler: GetContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        await make_contact(7777, 9601)

        result = await handler.handle(
            GetContactsQuery(owner_id=OWNER_ID, user_jwt_data=user_jwt)
        )

        assert result.contacts == []


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestSearchContactsQuery:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> SearchContactsQueryHandler:
        return await request_container.get(SearchContactsQueryHandler)

    async def test_username_search_finds_a_stranger(
        self,
        handler: SearchContactsQueryHandler,
        user_jwt: UserJWTData,
        make_profile,
    ) -> None:
        await make_profile(9701, "stranger", "Stranger")

        result = await handler.handle(
            SearchContactsQuery(owner_id=OWNER_ID, query="@stranger", user_jwt_data=user_jwt)
        )

        assert len(result.items) == 1
        assert result.items[0].user_id == 9701
        assert result.items[0].profile is not None
        assert result.items[0].profile.display_name == "Stranger"
        assert result.items[0].contact is None

    async def test_username_search_marks_an_existing_contact(
        self,
        handler: SearchContactsQueryHandler,
        user_jwt: UserJWTData,
        make_profile,
        make_contact,
    ) -> None:
        await make_profile(9702, "known")
        await make_contact(OWNER_ID, 9702, first_name="Знакомый")

        result = await handler.handle(
            SearchContactsQuery(owner_id=OWNER_ID, query="@known", user_jwt_data=user_jwt)
        )

        assert result.items[0].contact is not None
        assert result.items[0].contact.first_name == "Знакомый"

    async def test_unknown_username_gives_nothing(
        self, handler: SearchContactsQueryHandler, user_jwt: UserJWTData
    ) -> None:
        result = await handler.handle(
            SearchContactsQuery(owner_id=OWNER_ID, query="@nobody", user_jwt_data=user_jwt)
        )

        assert result.items == []

    async def test_prefix_search_stays_inside_my_contacts(
        self,
        handler: SearchContactsQueryHandler,
        user_jwt: UserJWTData,
        make_profile,
        make_contact,
    ) -> None:
        await make_profile(9801, "mine", "Мария")
        await make_profile(9802, "notmine", "Марина")
        await make_contact(OWNER_ID, 9801)

        result = await handler.handle(
            SearchContactsQuery(owner_id=OWNER_ID, query="Мар", user_jwt_data=user_jwt)
        )

        assert [item.user_id for item in result.items] == [9801]

    async def test_prefix_search_also_matches_the_local_name(
        self,
        handler: SearchContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        await make_contact(OWNER_ID, 9803, first_name="Петя")

        result = await handler.handle(
            SearchContactsQuery(owner_id=OWNER_ID, query="Пет", user_jwt_data=user_jwt)
        )

        assert [item.user_id for item in result.items] == [9803]

    async def test_too_short_prefix_is_ignored(
        self,
        handler: SearchContactsQueryHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        await make_contact(OWNER_ID, 9804, first_name="Петя")

        result = await handler.handle(
            SearchContactsQuery(owner_id=OWNER_ID, query="П", user_jwt_data=user_jwt)
        )

        assert result.items == []


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestGetBlockedUsersQuery:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> GetBlockedUsersQueryHandler:
        return await request_container.get(GetBlockedUsersQueryHandler)

    async def test_blocked_users_are_listed_with_profiles(
        self,
        handler: GetBlockedUsersQueryHandler,
        user_jwt: UserJWTData,
        make_profile,
        make_block,
    ) -> None:
        await make_profile(9901, "blocked", "Blocked")
        await make_block(OWNER_ID, 9901)

        result = await handler.handle(
            GetBlockedUsersQuery(owner_id=OWNER_ID, user_jwt_data=user_jwt)
        )

        assert result.has_next is False
        assert result.blocked[0].target_id == 9901
        assert result.blocked[0].profile is not None
        assert result.blocked[0].profile.id == 9901
        assert result.blocked[0].profile.display_name == "Blocked"

    async def test_list_is_paged_by_cursor(
        self,
        handler: GetBlockedUsersQueryHandler,
        user_jwt: UserJWTData,
        make_block,
    ) -> None:
        for target_id in (9911, 9912):
            await make_block(OWNER_ID, target_id)

        first = await handler.handle(
            GetBlockedUsersQuery(owner_id=OWNER_ID, limit=1, user_jwt_data=user_jwt)
        )
        second = await handler.handle(
            GetBlockedUsersQuery(
                owner_id=OWNER_ID,
                limit=1,
                after_target_id=first.next_target_id,
                user_jwt_data=user_jwt,
            )
        )

        assert first.has_next is True
        assert [b.target_id for b in first.blocked] == [9911]
        assert [b.target_id for b in second.blocked] == [9912]
