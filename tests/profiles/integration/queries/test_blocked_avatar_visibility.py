import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.commands.contacts.block import BlockUserCommand, BlockUserCommandHandler
from app.profiles.queries.contacts.get_list import GetContactsQuery, GetContactsQueryHandler
from app.profiles.queries.contacts.search import SearchContactsQuery, SearchContactsQueryHandler
from app.profiles.queries.profiles.get_by_id import GetProfileByIdQuery, GetProfileByIdQueryHandler
from app.profiles.queries.profiles.get_list import GetProfilesQuery, GetProfilesQueryHandler
from app.profiles.schemas.profiles.requests import GetProfilesRequest

AVATARS = {"64": {"jpg": "9001/64.jpg"}}

BLOCKER_ID = 9001
VIEWER_ID = 9002


@pytest.fixture
async def blocker(make_profile, db_session: AsyncSession):
    profile = await make_profile(BLOCKER_ID, "blocker_user", "Blocker")
    profile.avatars = AVATARS
    await db_session.commit()
    return profile


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestBlockedViewerDoesNotSeeAvatar:

    async def test_profile_by_id(
        self,
        request_container: AsyncContainer,
        blocker,
        make_user_jwt,
    ) -> None:
        handler = await request_container.get(GetProfileByIdQueryHandler)
        before = await handler.handle(GetProfileByIdQuery(BLOCKER_ID, user_jwt_data=make_user_jwt(id=str(VIEWER_ID))))
        assert before.avatars

        block = await request_container.get(BlockUserCommandHandler)
        await block.handle(BlockUserCommand(owner_id=BLOCKER_ID, target_id=VIEWER_ID))

        blocked = await handler.handle(GetProfileByIdQuery(BLOCKER_ID, user_jwt_data=make_user_jwt(id=str(VIEWER_ID))))
        other = await handler.handle(GetProfileByIdQuery(BLOCKER_ID, user_jwt_data=make_user_jwt(id="9003")))
        owner = await handler.handle(GetProfileByIdQuery(BLOCKER_ID, user_jwt_data=make_user_jwt(id=str(BLOCKER_ID))))

        assert blocked.avatars == {}
        assert other.avatars
        assert owner.avatars

    async def test_profile_search(
        self,
        request_container: AsyncContainer,
        blocker,
        make_block,
    ) -> None:
        await make_block(BLOCKER_ID, VIEWER_ID)
        handler = await request_container.get(GetProfilesQueryHandler)
        request = GetProfilesRequest(q="blocker")

        result = await handler.handle(GetProfilesQuery(request.to_profile_filter(), viewer_id=VIEWER_ID, query=request.q))

        assert [profile.id for profile in result.items] == [BLOCKER_ID]
        assert result.items[0].avatars == {}

    async def test_contacts_list_and_search(
        self,
        request_container: AsyncContainer,
        blocker,
        make_block,
        make_contact,
    ) -> None:
        await make_contact(VIEWER_ID, BLOCKER_ID)
        await make_block(BLOCKER_ID, VIEWER_ID)

        contacts = await (await request_container.get(GetContactsQueryHandler)).handle(
            GetContactsQuery(owner_id=VIEWER_ID)
        )
        search = await (await request_container.get(SearchContactsQueryHandler)).handle(
            SearchContactsQuery(owner_id=VIEWER_ID, query="@blocker_user")
        )

        assert contacts.contacts[0].profile is not None
        assert contacts.contacts[0].profile.avatars == {}
        assert search.items[0].profile is not None
        assert search.items[0].profile.avatars == {}
