import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.models.chat import Chat, ChatType
from app.chats.models.profile import ChatUserProfile
from app.chats.queries.chats.get_list import GetListChatUserQuery, GetListChatUserQueryHandler
from app.core.services.auth.dto import UserJWTData


@pytest.fixture
async def list_handler(request_container: AsyncContainer) -> GetListChatUserQueryHandler:
    return await request_container.get(GetListChatUserQueryHandler)


@pytest.fixture
def create_chat_profile(db_session: AsyncSession):
    async def _factory(
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
        avatar_s3_key: str | None = None,
    ) -> ChatUserProfile:
        profile = ChatUserProfile.create(
            user_id=user_id,
            username=username or f"user{user_id}",
            display_name=display_name or f"User {user_id}",
            avatar_s3_key=avatar_s3_key,
        )
        db_session.add(profile)
        await db_session.commit()
        return profile

    return _factory


@pytest.fixture
def create_chat(db_session: AsyncSession, user_jwt: UserJWTData):
    async def _factory(
        members: list[int],
        chat_type: ChatType = ChatType.DIRECT,
        name: str | None = None,
    ) -> Chat:
        chat = Chat.create(
            created_by=int(user_jwt.id),
            members_ids=members,
            chat_type=chat_type,
            name=name,
        )
        db_session.add(chat)
        await db_session.commit()
        await db_session.refresh(chat)
        return chat

    return _factory


def _chat_of(result, chat_id):
    (chat,) = [c for c in result.chats if c.id == chat_id]
    return chat


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestDirectChatPeer:

    async def test_empty_direct_chat_still_carries_the_peer(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        create_chat_profile,
        user_jwt: UserJWTData,
    ) -> None:
        await create_chat_profile(2, username="peer", display_name="Peer Two")
        chat = await create_chat(members=[2], chat_type=ChatType.DIRECT)

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        listed = _chat_of(result, chat.id)
        # Ровно тот случай, ради которого поле заводилось: ни имени, ни аватара,
        # ни последнего сообщения — и раньше отрисовать диалог было нечем.
        assert listed.name is None
        assert listed.avatar_s3_key is None
        assert listed.last_message is None
        assert listed.peer is not None
        assert listed.peer.user_id == 2
        assert listed.peer.username == "peer"
        assert listed.peer.display_name == "Peer Two"

    async def test_peer_is_the_counterpart_not_me(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        create_chat_profile,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await create_chat_profile(1)
        await create_chat_profile(7)
        chat = await create_chat(members=[7], chat_type=ChatType.DIRECT)

        mine = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )
        theirs = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=make_user_jwt(id="7"), limit=10)
        )

        assert _chat_of(mine, chat.id).peer.user_id == 7
        assert _chat_of(theirs, chat.id).peer.user_id == 1

    async def test_peer_survives_a_missing_profile_projection(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        user_jwt: UserJWTData,
    ) -> None:
        # Профиль заводит консьюмер по profiles.profile.created и может отставать.
        chat = await create_chat(members=[404], chat_type=ChatType.DIRECT)

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        peer = _chat_of(result, chat.id).peer
        assert peer is not None
        assert peer.user_id == 404
        assert peer.username is None
        assert peer.display_name is None

    async def test_peer_avatar_comes_back_presigned(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        create_chat_profile,
        user_jwt: UserJWTData,
    ) -> None:
        await create_chat_profile(2, avatar_s3_key="avatars/2.jpg")
        chat = await create_chat(members=[2], chat_type=ChatType.DIRECT)

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        peer = _chat_of(result, chat.id).peer
        assert peer is not None
        assert peer.avatar_s3_key == "avatars/2.jpg"
        assert peer.avatar_url is not None
        assert peer.avatar_url.startswith("http")

    async def test_group_has_no_peer(
        self,
        list_handler: GetListChatUserQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        assert _chat_of(result, group_chat.id).peer is None

    async def test_channel_has_neither_peer_nor_preview(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_chat(members=[2, 3], chat_type=ChatType.CHANNEL, name="News")

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        listed = _chat_of(result, chat.id)
        assert listed.peer is None
        assert listed.members_preview == []


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestGroupMembersPreview:

    async def test_preview_is_capped_ordered_and_excludes_me(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        create_chat_profile,
        user_jwt: UserJWTData,
    ) -> None:
        for user_id in (2, 3, 4, 5):
            await create_chat_profile(user_id)
        chat = await create_chat(members=[5, 4, 3, 2], chat_type=ChatType.GROUP, name="Crowd")

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        preview = _chat_of(result, chat.id).members_preview
        assert len(preview) == chat_config.CHAT_MEMBERS_PREVIEW_LIMIT
        assert [p.user_id for p in preview] == [2, 3, 4]
        assert int(user_jwt.id) not in {p.user_id for p in preview}

    async def test_direct_chat_has_no_members_preview(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_chat(members=[2], chat_type=ChatType.DIRECT)

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        assert _chat_of(result, chat.id).members_preview == []

    async def test_preview_avatars_are_presigned(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        create_chat_profile,
        user_jwt: UserJWTData,
    ) -> None:
        await create_chat_profile(2, avatar_s3_key="avatars/2.jpg")
        chat = await create_chat(members=[2, 3], chat_type=ChatType.GROUP, name="Pics")

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        preview = _chat_of(result, chat.id).members_preview
        (with_avatar,) = [p for p in preview if p.user_id == 2]
        assert with_avatar.avatar_url is not None
        assert with_avatar.avatar_url.startswith("http")


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatListQueryBudget:

    async def test_query_count_does_not_grow_with_the_page_size(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        create_chat_profile,
        count_sql,
        user_jwt: UserJWTData,
    ) -> None:
        await create_chat(members=[2], chat_type=ChatType.DIRECT)

        with count_sql() as one_chat:
            result = await list_handler.handle(
                GetListChatUserQuery(user_jwt_data=user_jwt, limit=50)
            )
        assert len(result.chats) == 1

        for user_id in range(3, 12):
            await create_chat_profile(user_id)
            await create_chat(members=[user_id], chat_type=ChatType.DIRECT)

        with count_sql() as ten_chats:
            result = await list_handler.handle(
                GetListChatUserQuery(user_jwt_data=user_jwt, limit=50)
            )
        assert len(result.chats) == 10
        assert all(chat.peer is not None for chat in result.chats)

        # keyset-страница + пины + один добор собеседников — и это не зависит от N.
        assert len(one_chat) == 3
        assert len(ten_chats) == len(one_chat)

    async def test_mixed_page_still_takes_one_counterpart_query(
        self,
        list_handler: GetListChatUserQueryHandler,
        create_chat,
        count_sql,
        user_jwt: UserJWTData,
    ) -> None:
        await create_chat(members=[2], chat_type=ChatType.DIRECT)
        await create_chat(members=[3, 4], chat_type=ChatType.GROUP, name="G1")
        await create_chat(members=[5, 6], chat_type=ChatType.GROUP, name="G2")
        await create_chat(members=[7], chat_type=ChatType.CHANNEL, name="C1")

        with count_sql() as statements:
            result = await list_handler.handle(
                GetListChatUserQuery(user_jwt_data=user_jwt, limit=50)
            )

        assert len(result.chats) == 4
        assert len(statements) == 3
