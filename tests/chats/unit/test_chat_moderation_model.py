from datetime import timedelta

import pytest

from app.chats.exceptions import (
    AccessDeniedChatError,
    ChatUsernameNotAllowedError,
    InvalidChatUsernameError,
    InvalidOwnershipTransferError,
)
from app.chats.models.chat import (
    Chat,
    ChatType,
    LeftChatMemberEvent,
    MutedChatMemberEvent,
    TransferredChatOwnershipEvent,
    UpdatedChatEvent,
)
from app.chats.models.chat_members import PERMANENT_UNTIL, ChatMember
from app.chats.models.chat_roles import ChatRoleId
from app.core.utils import now_utc


def make_chat(chat_type: ChatType = ChatType.GROUP, is_public: bool = True) -> Chat:
    chat = Chat.create(
        created_by=1,
        members_ids=[2, 3],
        chat_type=chat_type,
        name="Moderated",
        is_public=is_public,
    ) if chat_type != ChatType.DIRECT else Chat.create(
        created_by=1, members_ids=[2], chat_type=ChatType.DIRECT
    )
    chat.pull_events()
    return chat


def member_of(chat: Chat, user_id: int) -> ChatMember:
    return next(member for member in chat.members if member.user_id == user_id)


@pytest.mark.unit
@pytest.mark.chats
class TestChatUsername:
    @pytest.mark.parametrize("username", ["durov", "My_Channel1", "a" * 32, "@news_room"])
    def test_valid_usernames(self, username: str) -> None:
        assert Chat.validate_username(username) == username.removeprefix("@")

    @pytest.mark.parametrize(
        ("username", "reason"),
        [
            ("abcd", "length"),
            ("a" * 33, "length"),
            ("1abcde", "format"),
            ("abcde_", "format"),
            ("abc-de", "format"),
            ("тест_канал", "format"),
            ("Support", "reserved"),
        ],
    )
    def test_invalid_usernames(self, username: str, reason: str) -> None:
        with pytest.raises(InvalidChatUsernameError) as exc:
            Chat.validate_username(username)
        assert exc.value.reason == reason

    def test_set_username_on_public_group_registers_update(self) -> None:
        chat = make_chat()

        chat.set_username(updated_by=1, username="Python_News")

        assert chat.username == "Python_News"
        event = chat.pull_events()[-1]
        assert isinstance(event, UpdatedChatEvent)
        assert event.username == "Python_News"

    def test_private_chat_cannot_have_username(self) -> None:
        chat = make_chat(is_public=False)

        with pytest.raises(ChatUsernameNotAllowedError) as exc:
            chat.set_username(updated_by=1, username="private_one")
        assert exc.value.reason == "chat_not_public"

    def test_direct_chat_cannot_have_username(self) -> None:
        chat = make_chat(ChatType.DIRECT)

        with pytest.raises(ChatUsernameNotAllowedError) as exc:
            chat.set_username(updated_by=1, username="direct_one")
        assert exc.value.reason == "direct_chat"

    def test_making_chat_private_releases_username(self) -> None:
        chat = make_chat()
        chat.set_username(updated_by=1, username="soon_private")

        chat.update(updated_by=1, name=None, description=None, is_public=False)

        assert chat.username is None
        event = chat.pull_events()[-1]
        assert isinstance(event, UpdatedChatEvent)
        assert event.username is None


@pytest.mark.unit
@pytest.mark.chats
class TestChatAvatar:
    def test_update_avatar_picks_small_jpg_as_key(self) -> None:
        chat = make_chat()
        avatars = {
            "64": {"jpg": "http://s3/chat-avatars/x/64.jpg", "webp": "http://s3/chat-avatars/x/64.webp"},
            "512": {"jpg": "http://s3/chat-avatars/x/512.jpg"},
        }

        chat.update_avatar(updated_by=1, avatars=avatars)

        assert chat.avatars == avatars
        assert chat.avatar_s3_key == "http://s3/chat-avatars/x/64.jpg"
        event = chat.pull_events()[-1]
        assert isinstance(event, UpdatedChatEvent)
        assert event.avatars == avatars

    def test_removing_avatar_clears_key(self) -> None:
        chat = make_chat()
        chat.update_avatar(updated_by=1, avatars={"64": {"jpg": "http://s3/a.jpg"}})

        chat.update_avatar(updated_by=1, avatars={})

        assert chat.avatars == {}
        assert chat.avatar_s3_key is None


@pytest.mark.unit
@pytest.mark.chats
class TestOwnershipTransfer:
    def test_transfer_moves_created_by_and_owner_role(self) -> None:
        chat = make_chat()
        target = member_of(chat, 2)

        previous = chat.transfer_ownership(requester_id=1, new_owner=target)

        assert previous == 1
        assert chat.created_by == 2
        assert target.role_id == ChatRoleId.OWNER
        event = chat.pull_events()[-1]
        assert isinstance(event, TransferredChatOwnershipEvent)
        assert (event.previous_owner_id, event.new_owner_id) == (1, 2)

    def test_previous_owner_can_leave_and_new_owner_cannot(self) -> None:
        chat = make_chat()
        chat.transfer_ownership(requester_id=1, new_owner=member_of(chat, 2))

        chat.leave(user_id=1)
        assert isinstance(chat.pull_events()[-1], LeftChatMemberEvent)

        with pytest.raises(AccessDeniedChatError):
            chat.leave(user_id=2)

    def test_cannot_transfer_direct_chat(self) -> None:
        chat = make_chat(ChatType.DIRECT)

        with pytest.raises(InvalidOwnershipTransferError) as exc:
            chat.transfer_ownership(requester_id=1, new_owner=member_of(chat, 2))
        assert exc.value.reason == "direct_chat"

    def test_cannot_transfer_to_current_owner(self) -> None:
        chat = make_chat()

        with pytest.raises(InvalidOwnershipTransferError) as exc:
            chat.transfer_ownership(requester_id=1, new_owner=member_of(chat, 1))
        assert exc.value.reason == "already_owner"

    def test_cannot_transfer_to_banned_member(self) -> None:
        chat = make_chat()
        target = member_of(chat, 2)
        target.banned_until = PERMANENT_UNTIL

        with pytest.raises(InvalidOwnershipTransferError) as exc:
            chat.transfer_ownership(requester_id=1, new_owner=target)
        assert exc.value.reason == "target_banned"
        assert chat.created_by == 1


@pytest.mark.unit
@pytest.mark.chats
class TestMemberMute:
    def test_mute_event_carries_deadline(self) -> None:
        chat = make_chat()
        target = member_of(chat, 2)
        until = now_utc() + timedelta(hours=1)

        target.mute(until)
        chat.mute_member(target, requester_id=1)

        event = chat.pull_events()[-1]
        assert isinstance(event, MutedChatMemberEvent)
        assert event.mute is True
        assert event.muted_until == until.isoformat()

    def test_unmute_event(self) -> None:
        chat = make_chat()
        target = member_of(chat, 2)
        target.mute(None)

        target.unmute()
        chat.mute_member(target, requester_id=1)

        event = chat.pull_events()[-1]
        assert isinstance(event, MutedChatMemberEvent)
        assert event.mute is False
        assert event.muted_until is None

    def test_cannot_mute_self(self) -> None:
        chat = make_chat()

        with pytest.raises(AccessDeniedChatError):
            chat.mute_member(member_of(chat, 1), requester_id=1)
