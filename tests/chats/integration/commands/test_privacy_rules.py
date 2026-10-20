import pytest
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.calls.join import JoinCallCommand, JoinCallCommandHandler
from app.chats.commands.chats.add_member import AddMemberCommand, AddMemberCommandHandler
from app.chats.commands.chats.create import CreateChatCommand, CreateChatCommandHandler
from app.chats.commands.messages.send import SendMessageCommand, SendMessageCommandHandler
from app.chats.config import chat_config
from app.chats.exceptions import (
    CallsPrivacyRestrictedError,
    MessagesPrivacyRestrictedError,
    UserBlockedError,
    UserPrivacyRestrictedError,
)
from app.chats.models.blocks import ChatUserBlock
from app.chats.models.chat import Chat, ChatType
from app.chats.models.privacy import ChatUserContact, ChatUserPrivacyException
from app.chats.models.profile import ChatUserProfile
from app.chats.queries.chats.get_members import GetChatMembersQuery, GetChatMembersQueryHandler
from app.chats.queries.messages.get_list import GetMessagesQuery, GetMessagesQueryHandler
from app.privacy.utils import PrivacyRule
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
def set_privacy(db_session: AsyncSession):
    """Проекция настроек приватности — то, что в проде наполняет консьюмер."""

    async def _set(user_id: int, *, avatar: bool = False, **rules: str) -> None:
        profile = await db_session.get(ChatUserProfile, user_id)
        if profile is None:
            profile = ChatUserProfile.create(
                user_id=user_id,
                username=f"user{user_id}",
                avatar_s3_key=AVATAR_KEY.format(user_id=user_id) if avatar else None,
            )
            db_session.add(profile)

        for rule, visibility in rules.items():
            setattr(profile, f"privacy_{rule}", visibility)

        await db_session.commit()

    return _set


@pytest.fixture
def add_contact(db_session: AsyncSession):
    async def _add(owner_id: int, contact_id: int) -> None:
        db_session.add(ChatUserContact(owner_id=owner_id, contact_id=contact_id))
        await db_session.commit()

    return _add


@pytest.fixture
def set_exception(db_session: AsyncSession):
    async def _set(owner_id: int, rule: PrivacyRule, target_id: int, allow: bool) -> None:
        db_session.add(
            ChatUserPrivacyException(
                owner_id=owner_id, rule=rule.value, target_id=target_id, allow=allow
            )
        )
        await db_session.commit()

    return _set


@pytest.fixture
def block(db_session: AsyncSession):
    async def _block(owner_id: int, target_id: int) -> None:
        db_session.add(ChatUserBlock(owner_id=owner_id, target_id=target_id))
        await db_session.commit()

    return _block


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessagesPrivacy:

    async def test_nobody_cannot_write_to_the_direct(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, messages="nobody")
        send = await request_container.get(SendMessageCommandHandler)

        with pytest.raises(MessagesPrivacyRestrictedError) as exc:
            await send.handle(SendMessageCommand(
                chat_id=direct_chat.id, content="hi", user_jwt_data=make_user_jwt(id="2"),
            ))
        assert exc.value.user_id == 1

    async def test_owner_still_writes_to_the_same_direct(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        user_jwt: UserJWTData,
    ) -> None:
        """Настройка односторонняя: она закрывает входящие, а не исходящие."""
        await set_privacy(1, messages="nobody")
        await set_privacy(2, messages="everybody")
        send = await request_container.get(SendMessageCommandHandler)

        message = await send.handle(SendMessageCommand(
            chat_id=direct_chat.id, content="still mine", user_jwt_data=user_jwt,
        ))
        assert message.content == "still mine"

    async def test_contacts_only_lets_a_contact_through(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        add_contact,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, messages="contacts")
        send = await request_container.get(SendMessageCommandHandler)

        with pytest.raises(MessagesPrivacyRestrictedError):
            await send.handle(SendMessageCommand(
                chat_id=direct_chat.id, content="before", user_jwt_data=make_user_jwt(id="2"),
            ))

        await add_contact(owner_id=1, contact_id=2)
        message = await send.handle(SendMessageCommand(
            chat_id=direct_chat.id, content="after", user_jwt_data=make_user_jwt(id="2"),
        ))
        assert message.content == "after"

    async def test_personal_exception_beats_the_rule(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        set_exception,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, messages="nobody")
        await set_exception(1, PrivacyRule.MESSAGES, 2, allow=True)
        send = await request_container.get(SendMessageCommandHandler)

        message = await send.handle(SendMessageCommand(
            chat_id=direct_chat.id, content="allowed", user_jwt_data=make_user_jwt(id="2"),
        ))
        assert message.content == "allowed"

    async def test_deny_exception_closes_an_open_rule(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        set_exception,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, messages="everybody")
        await set_exception(1, PrivacyRule.MESSAGES, 2, allow=False)
        send = await request_container.get(SendMessageCommandHandler)

        with pytest.raises(MessagesPrivacyRestrictedError):
            await send.handle(SendMessageCommand(
                chat_id=direct_chat.id, content="nope", user_jwt_data=make_user_jwt(id="2"),
            ))

    async def test_block_is_reported_before_privacy(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        block,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, messages="nobody")
        await block(owner_id=1, target_id=2)
        send = await request_container.get(SendMessageCommandHandler)

        with pytest.raises(UserBlockedError):
            await send.handle(SendMessageCommand(
                chat_id=direct_chat.id, content="hi", user_jwt_data=make_user_jwt(id="2"),
            ))

    async def test_group_is_not_affected(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        set_privacy,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, messages="nobody")
        send = await request_container.get(SendMessageCommandHandler)

        message = await send.handle(SendMessageCommand(
            chat_id=group_chat.id, content="group is fine", user_jwt_data=make_user_jwt(id="2"),
        ))
        assert message.content == "group is fine"

    async def test_new_direct_is_refused(
        self,
        request_container: AsyncContainer,
        set_privacy,
        user_jwt: UserJWTData,
    ) -> None:
        await set_privacy(91, messages="nobody")
        create = await request_container.get(CreateChatCommandHandler)

        with pytest.raises(MessagesPrivacyRestrictedError) as exc:
            await create.handle(CreateChatCommand(
                name=None, description=None, chat_type=ChatType.DIRECT,
                member_ids=[91], is_public=False, user_jwt_data=user_jwt,
            ))
        assert exc.value.user_id == 91


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestCallsAndInvitesPrivacy:

    async def test_calls_nobody_refuses_the_join(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, calls="nobody")
        join = await request_container.get(JoinCallCommandHandler)

        with pytest.raises(CallsPrivacyRestrictedError) as exc:
            await join.handle(JoinCallCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=direct_chat.id
            ))
        assert exc.value.user_id == 1

    async def test_messages_open_calls_closed(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        set_privacy,
        make_user_jwt,
    ) -> None:
        """Оси независимы: писать можно, звонить — нет."""
        await set_privacy(1, messages="everybody", calls="nobody")
        send = await request_container.get(SendMessageCommandHandler)
        join = await request_container.get(JoinCallCommandHandler)

        await send.handle(SendMessageCommand(
            chat_id=direct_chat.id, content="ping", user_jwt_data=make_user_jwt(id="2"),
        ))
        with pytest.raises(CallsPrivacyRestrictedError):
            await join.handle(JoinCallCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=direct_chat.id
            ))

    async def test_group_invites_nobody_blocks_add_member(
        self,
        request_container: AsyncContainer,
        create_group_chat,
        set_privacy,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat(members=[2])
        await set_privacy(79, group_invites="nobody")
        add = await request_container.get(AddMemberCommandHandler)

        with pytest.raises(UserPrivacyRestrictedError) as exc:
            await add.handle(AddMemberCommand(
                user_jwt_data=user_jwt, chat_id=chat.id, target_user_id=79, role_id=5,
            ))
        assert exc.value.user_ids == [79]

    async def test_group_invites_contacts_allows_a_contact(
        self,
        request_container: AsyncContainer,
        create_group_chat,
        set_privacy,
        add_contact,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat(members=[2])
        await set_privacy(82, group_invites="contacts")
        await add_contact(owner_id=82, contact_id=int(user_jwt.id))
        add = await request_container.get(AddMemberCommandHandler)

        await add.handle(AddMemberCommand(
            user_jwt_data=user_jwt, chat_id=chat.id, target_user_id=82, role_id=5,
        ))

    async def test_group_creation_reports_every_restricted_member(
        self,
        request_container: AsyncContainer,
        set_privacy,
        user_jwt: UserJWTData,
    ) -> None:
        await set_privacy(83, group_invites="nobody")
        await set_privacy(84, group_invites="contacts")
        create = await request_container.get(CreateChatCommandHandler)

        with pytest.raises(UserPrivacyRestrictedError) as exc:
            await create.handle(CreateChatCommand(
                name="Party", description=None, chat_type=ChatType.GROUP,
                member_ids=[83, 84, 85], is_public=False, user_jwt_data=user_jwt,
            ))
        assert exc.value.user_ids == [83, 84]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestPhotoAndLastSeenPrivacy:

    async def test_photo_nobody_hides_the_avatar_but_not_presence(
        self,
        request_container: AsyncContainer,
        redis_client: Redis,
        group_chat: Chat,
        set_privacy,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, avatar=True, photo="nobody")
        await set_privacy(3, avatar=True)
        presence = PresenceService(redis=redis_client)
        await presence.set_online(1)
        await presence.set_online(3)

        handler = await request_container.get(GetChatMembersQueryHandler)
        result = await handler.handle(GetChatMembersQuery(
            user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, include_presence=True,
        ))

        profiles = {member.user_id: member.profile for member in result.members}
        assert profiles[1] is not None and profiles[1].avatar_url is None
        assert profiles[3] is not None and is_signed_avatar(profiles[3].avatar_url, 3)

        online = {item.user_id: item.is_online for item in result.presence}
        assert online[1] is True
        assert online[3] is True

    async def test_last_seen_nobody_hides_presence_but_not_the_avatar(
        self,
        request_container: AsyncContainer,
        redis_client: Redis,
        group_chat: Chat,
        set_privacy,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, avatar=True, last_seen="nobody")
        presence = PresenceService(redis=redis_client)
        await presence.set_online(1)

        handler = await request_container.get(GetChatMembersQueryHandler)
        result = await handler.handle(GetChatMembersQuery(
            user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, include_presence=True,
        ))

        profile = next(member.profile for member in result.members if member.user_id == 1)
        assert profile is not None and is_signed_avatar(profile.avatar_url, 1)
        online = {item.user_id: item.is_online for item in result.presence}
        assert online[1] is False

    async def test_photo_contacts_shows_it_to_a_contact_only(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        set_privacy,
        add_contact,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, avatar=True, photo="contacts")
        handler = await request_container.get(GetChatMembersQueryHandler)

        hidden = await handler.handle(GetChatMembersQuery(
            user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id,
        ))
        assert next(
            member.profile for member in hidden.members if member.user_id == 1
        ).avatar_url is None

        await add_contact(owner_id=1, contact_id=2)
        visible = await handler.handle(GetChatMembersQuery(
            user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id,
        ))
        assert is_signed_avatar(next(
            member.profile for member in visible.members if member.user_id == 1
        ).avatar_url, 1)

    async def test_own_photo_is_always_visible(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        set_privacy,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        """Автор видит своё фото при любой настройке: себя приватность не касается."""
        await set_privacy(1, avatar=True, photo="nobody")
        await create_message(group_chat, user_jwt, "mine")

        handler = await request_container.get(GetMessagesQueryHandler)
        result = await handler.handle(GetMessagesQuery(
            user_jwt_data=user_jwt, chat_id=group_chat.id,
        ))

        profile = result.messages[0].profile
        assert profile is not None and is_signed_avatar(profile.avatar_url, 1)

    async def test_photo_is_hidden_from_other_message_authors_view(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        set_privacy,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await set_privacy(1, avatar=True, photo="nobody")
        await create_message(group_chat, user_jwt, "from me")

        handler = await request_container.get(GetMessagesQueryHandler)
        result = await handler.handle(GetMessagesQuery(
            user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id,
        ))

        profile = result.messages[0].profile
        assert profile is not None
        assert profile.avatar_url is None
        assert profile.avatar_s3_key is None
