import pytest
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.calls.join import JoinCallCommand, JoinCallCommandHandler
from app.chats.commands.chats.add_member import AddMemberCommand, AddMemberCommandHandler
from app.chats.commands.chats.create import CreateChatCommand, CreateChatCommandHandler
from app.chats.commands.messages.forward import ForwardMessageCommand, ForwardMessageCommandHandler
from app.chats.commands.messages.send import SendMessageCommand, SendMessageCommandHandler
from app.chats.config import chat_config
from app.chats.exceptions import UserBlockedError, UserPrivacyRestrictedError
from app.chats.models.blocks import ChatUserBlock
from app.chats.models.chat import Chat, ChatType
from app.chats.models.profile import ChatUserProfile
from app.chats.queries.chats.get_list import GetListChatUserQuery, GetListChatUserQueryHandler
from app.chats.queries.chats.get_members import GetChatMembersQuery, GetChatMembersQueryHandler
from app.chats.queries.messages.get_list import GetMessagesQuery, GetMessagesQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.websocket.presence import PresenceService
from tests.support.http import assert_presigned_url

AVATAR_KEY = "{user_id}/64.jpg"


def is_signed_avatar(url: str | None, user_id: int) -> bool:
    """Аватар профиля приватный: в проекции ключ, наружу — подписанная ссылка на него."""
    key = AVATAR_KEY.format(user_id=user_id)
    assert_presigned_url(url or "", bucket=chat_config.AVATAR_BUCKET, file_key=key)
    return f"/{chat_config.AVATAR_BUCKET}/{key}?" in (url or "")


@pytest.fixture
def block(db_session: AsyncSession):
    async def _block(owner_id: int, target_id: int) -> None:
        db_session.add(ChatUserBlock(owner_id=owner_id, target_id=target_id))
        await db_session.commit()

    return _block


@pytest.fixture
def with_avatar(db_session: AsyncSession):
    async def _profile(user_id: int) -> None:
        db_session.add(ChatUserProfile.create(
            user_id=user_id,
            username=f"user{user_id}",
            avatar_s3_key=AVATAR_KEY.format(user_id=user_id),
        ))
        await db_session.commit()

    return _profile


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestBlockingInChats:

    async def test_blocked_user_cannot_write_to_blocker(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        block,
        make_user_jwt,
    ) -> None:
        await block(owner_id=1, target_id=2)
        send = await request_container.get(SendMessageCommandHandler)

        with pytest.raises(UserBlockedError) as exc:
            await send.handle(SendMessageCommand(
                chat_id=direct_chat.id, content="hello?", user_jwt_data=make_user_jwt(id="2"),
            ))
        assert exc.value.user_id == 1

    async def test_blocker_cannot_write_to_blocked_until_unblock(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        block,
        user_jwt: UserJWTData,
    ) -> None:
        await block(owner_id=1, target_id=2)
        send = await request_container.get(SendMessageCommandHandler)

        with pytest.raises(UserBlockedError):
            await send.handle(SendMessageCommand(
                chat_id=direct_chat.id, content="bye", user_jwt_data=user_jwt,
            ))

    async def test_group_messages_are_not_affected(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        block,
        make_user_jwt,
    ) -> None:
        await block(owner_id=1, target_id=2)
        send = await request_container.get(SendMessageCommandHandler)

        message = await send.handle(SendMessageCommand(
            chat_id=group_chat.id, content="still here", user_jwt_data=make_user_jwt(id="2"),
        ))
        assert message.content == "still here"

    async def test_forward_into_blocked_direct(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        direct_chat: Chat,
        block,
        create_message,
        make_user_jwt,
    ) -> None:
        source = await create_message(group_chat, make_user_jwt(id="3"), "forward me")
        await block(owner_id=2, target_id=1)
        forward = await request_container.get(ForwardMessageCommandHandler)

        with pytest.raises(UserBlockedError):
            await forward.handle(ForwardMessageCommand(
                user_jwt_data=make_user_jwt(id="1"),
                source_chat_id=group_chat.id,
                source_message_id=source.id,
                target_chat_id=direct_chat.id,
            ))

    async def test_blocked_user_cannot_call(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        block,
        make_user_jwt,
    ) -> None:
        await block(owner_id=1, target_id=2)
        join = await request_container.get(JoinCallCommandHandler)

        with pytest.raises(UserBlockedError):
            await join.handle(JoinCallCommand(user_jwt_data=make_user_jwt(id="2"), chat_id=direct_chat.id))

    async def test_blocked_user_cannot_add_blocker_to_group(
        self,
        request_container: AsyncContainer,
        create_group_chat,
        block,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat(members=[2])
        await block(owner_id=77, target_id=int(user_jwt.id))
        add = await request_container.get(AddMemberCommandHandler)

        with pytest.raises(UserPrivacyRestrictedError) as exc:
            await add.handle(AddMemberCommand(
                user_jwt_data=user_jwt, chat_id=chat.id, target_user_id=77, role_id=5,
            ))
        assert exc.value.user_ids == [77]

    async def test_blocker_can_still_add_blocked_user(
        self,
        request_container: AsyncContainer,
        create_group_chat,
        block,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat(members=[2])
        await block(owner_id=int(user_jwt.id), target_id=78)
        add = await request_container.get(AddMemberCommandHandler)

        await add.handle(AddMemberCommand(
            user_jwt_data=user_jwt, chat_id=chat.id, target_user_id=78, role_id=5,
        ))

    async def test_group_creation_with_blocker_is_restricted(
        self,
        request_container: AsyncContainer,
        block,
        user_jwt: UserJWTData,
    ) -> None:
        await block(owner_id=81, target_id=int(user_jwt.id))
        create = await request_container.get(CreateChatCommandHandler)

        with pytest.raises(UserPrivacyRestrictedError) as exc:
            await create.handle(CreateChatCommand(
                name="Party", description=None, chat_type=ChatType.GROUP,
                member_ids=[80, 81], is_public=False, user_jwt_data=user_jwt,
            ))
        assert exc.value.user_ids == [81]

    async def test_new_direct_with_blocker_is_refused(
        self,
        request_container: AsyncContainer,
        block,
        user_jwt: UserJWTData,
    ) -> None:
        await block(owner_id=90, target_id=int(user_jwt.id))
        create = await request_container.get(CreateChatCommandHandler)

        with pytest.raises(UserBlockedError):
            await create.handle(CreateChatCommand(
                name=None, description=None, chat_type=ChatType.DIRECT,
                member_ids=[90], is_public=False, user_jwt_data=user_jwt,
            ))


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestBlockingHidesPresenceAndPhoto:

    async def test_members_list_hides_blocker_photo_and_status(
        self,
        request_container: AsyncContainer,
        redis_client: Redis,
        group_chat: Chat,
        block,
        with_avatar,
        make_user_jwt,
    ) -> None:
        for user_id in (1, 3):
            await with_avatar(user_id)
        presence = PresenceService(redis=redis_client)
        await presence.set_online(1)
        await presence.set_online(3)
        await block(owner_id=1, target_id=2)

        handler = await request_container.get(GetChatMembersQueryHandler)
        result = await handler.handle(GetChatMembersQuery(
            user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, include_presence=True,
        ))

        profiles = {member.user_id: member.profile for member in result.members}
        assert profiles[1] is not None and profiles[1].avatar_url is None
        assert profiles[1].avatar_s3_key is None
        assert profiles[3] is not None and is_signed_avatar(profiles[3].avatar_url, 3)

        online = {item.user_id: item.is_online for item in result.presence}
        assert online[1] is False
        assert online[3] is True

    async def test_blocker_still_sees_blocked_user(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        block,
        with_avatar,
        user_jwt: UserJWTData,
    ) -> None:
        await with_avatar(2)
        await block(owner_id=1, target_id=2)

        handler = await request_container.get(GetChatMembersQueryHandler)
        result = await handler.handle(GetChatMembersQuery(user_jwt_data=user_jwt, chat_id=group_chat.id))

        profile = next(member.profile for member in result.members if member.user_id == 2)
        assert profile is not None and is_signed_avatar(profile.avatar_url, 2)

    async def test_chat_list_peer_photo_hidden(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        block,
        with_avatar,
        make_user_jwt,
    ) -> None:
        await with_avatar(1)
        await block(owner_id=1, target_id=2)

        handler = await request_container.get(GetListChatUserQueryHandler)
        result = await handler.handle(GetListChatUserQuery(user_jwt_data=make_user_jwt(id="2")))

        chat = next(item for item in result.chats if item.id == direct_chat.id)
        assert chat.peer is not None and chat.peer.user_id == 1
        assert chat.peer.avatar_url is None

    async def test_message_author_photo_hidden(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        block,
        with_avatar,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await with_avatar(1)
        await create_message(group_chat, user_jwt, "from the blocker")
        await block(owner_id=1, target_id=3)

        handler = await request_container.get(GetMessagesQueryHandler)
        hidden = await handler.handle(GetMessagesQuery(user_jwt_data=make_user_jwt(id="3"), chat_id=group_chat.id))
        visible = await handler.handle(GetMessagesQuery(user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id))

        assert hidden.messages[0].profile is not None
        assert hidden.messages[0].profile.avatar_url is None
        assert visible.messages[0].profile is not None
        assert is_signed_avatar(visible.messages[0].profile.avatar_url, 1)
