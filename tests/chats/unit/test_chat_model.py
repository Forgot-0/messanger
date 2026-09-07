import pytest

from app.chats.config import chat_config
from app.chats.exceptions import AccessDeniedChatError, MemberLimitExceededError, SlowModeOutOfRangeError
from app.chats.models.chat import (
    BannedChatMemberEvent,
    Chat,
    ChatFanoutStrategy,
    ChatType,
    CreatedChatEvent,
    DeletedChatEvent,
    KickedChatMemberEvent,
    LeftChatMemberEvent,
    UpdatedChatEvent,
)


def make_direct_chat(created_by: int = 1, other_member: int = 2) -> Chat:
    return Chat.create(
        created_by=created_by,
        members_ids=[created_by, other_member],
        chat_type=ChatType.DIRECT,
    )


def make_group_chat(created_by: int = 1, members_ids: list[int] | None = None) -> Chat:
    members_ids = members_ids or [created_by, 2, 3]
    return Chat.create(
        created_by=created_by,
        members_ids=members_ids,
        chat_type=ChatType.GROUP,
        name="Test Group",
        description="A test group chat",
        is_public=True,
        admin_only=False,
        slow_mode_seconds=0,
        permissions={"send": True},
    )


@pytest.mark.unit
@pytest.mark.chats
class TestChatModel:

    def test_create_direct_chat_populates_two_members_and_event(self) -> None:
        chat = make_direct_chat(created_by=1, other_member=2)

        assert chat.type == ChatType.DIRECT
        assert chat.member_count == 2
        assert len(chat.members) == 2
        assert {member.user_id for member in chat.members} == {1, 2}
        assert all(member.role_id == 4 for member in chat.members)

        events = chat.pull_events()
        assert len(events) == 3
        assert isinstance(events[2], CreatedChatEvent)
        assert events[2].created_by == 1
        assert events[2].member_ids == [2]
        assert events[2].chat_type == ChatType.DIRECT.value

    def test_create_group_chat_assigns_owner_and_members_roles(self) -> None:
        chat = make_group_chat(created_by=10, members_ids=[10, 20, 30])

        assert chat.type == ChatType.GROUP
        assert chat.member_count == 3
        assert len(chat.members) == 3

        owner = next(member for member in chat.members if member.user_id == 10)
        assert owner.role_id == 1

        others = [member for member in chat.members if member.user_id != 10]
        assert all(member.role_id == 5 for member in others)

    def test_create_channel_chat_assigns_channel_subscribers_role(self) -> None:
        chat = Chat.create(
            created_by=1,
            members_ids=[1, 2, 3],
            chat_type=ChatType.CHANNEL,
            name="Channel",
        )

        assert chat.type == ChatType.CHANNEL
        assert chat.member_count == 3
        assert len(chat.members) == 3

        owner = next(member for member in chat.members if member.user_id == 1)
        assert owner.role_id == 1

        subscribers = [member for member in chat.members if member.user_id != 1]
        assert all(member.role_id == 6 for member in subscribers)

    def test_create_direct_chat_with_wrong_participant_count_raises(self) -> None:
        with pytest.raises(MemberLimitExceededError):
            Chat.create(created_by=1, members_ids=[1], chat_type=ChatType.DIRECT)

    def test_create_group_chat_exceeding_limit_raises(self) -> None:
        too_many_members = [1] + list(range(2, chat_config.MAX_GROUP_MEMBERS + 2))

        with pytest.raises(MemberLimitExceededError) as exc_info:
            Chat.create(created_by=1, members_ids=too_many_members, chat_type=ChatType.GROUP)

        assert exc_info.value.limit == chat_config.MAX_GROUP_MEMBERS

    def test_create_with_invalid_slow_mode_raises(self) -> None:
        with pytest.raises(SlowModeOutOfRangeError):
            Chat.create(
                created_by=1,
                members_ids=[1, 2],
                chat_type=ChatType.GROUP,
                slow_mode_seconds=chat_config.MAX_SLOW_MODE_SECONDS + 1,
            )

    def test_update_changes_fields_and_registers_event(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])
        chat.pull_events()

        chat.update(
            updated_by=1,
            name="Updated name",
            description="Updated description",
            is_public=False,
            admin_only=True,
            slow_mode_seconds=123,
            permissions={"send": False},
        )

        assert chat.name == "Updated name"
        assert chat.description == "Updated description"
        assert chat.is_public is False
        assert chat.admin_only is True
        assert chat.slow_mode_seconds == 123
        assert chat.permissions == {"send": False}

        events = chat.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], UpdatedChatEvent)
        assert events[0].updated_by == 1
        assert events[0].name == "Updated name"

    def test_delete_marks_deleted_and_registers_event(self) -> None:
        chat = make_direct_chat()
        chat.pull_events()

        chat.delete(deleted_by=1)

        assert chat.is_deleted()
        events = chat.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], DeletedChatEvent)
        assert events[0].deleted_by == 1

    def test_leave_registers_event(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])
        chat.pull_events()

        chat.leave(user_id=2)

        # member_count сдвигает ChatRepository.shift_member_count одним UPDATE.
        events = chat.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], LeftChatMemberEvent)
        assert events[0].user_id == 2

    def test_leave_owner_raises_access_denied(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])

        with pytest.raises(AccessDeniedChatError):
            chat.leave(user_id=1)

    def test_kick_member_registers_event(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])
        chat.pull_events()

        chat.kick_member(target=2, requester_id=1)

        events = chat.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], KickedChatMemberEvent)
        assert events[0].target_user_id == 2
        assert events[0].requester_id == 1

    def test_kick_self_raises_access_denied(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])

        with pytest.raises(AccessDeniedChatError):
            chat.kick_member(target=1, requester_id=1)

    def test_ban_member_registers_event(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])
        chat.pull_events()

        chat.ban_member(target=2, requester_id=1, ban=True)

        events = chat.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], BannedChatMemberEvent)
        assert events[0].target_user_id == 2
        assert events[0].ban is True

    def test_ban_self_raises_access_denied(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2, 3])

        with pytest.raises(AccessDeniedChatError):
            chat.ban_member(target=1, requester_id=1, ban=True)

    def test_fanout_strategy_by_chat_type_and_size(self) -> None:
        direct = Chat(id=None, created_by=1, type=ChatType.DIRECT, member_count=2, permissions={}, name=None, description=None, is_public=False, admin_only=False, slow_mode_seconds=0)
        group_small = Chat(id=None, created_by=1, type=ChatType.GROUP, member_count=chat_config.FAN_OUT_WRITE_THRESHOLD, permissions={}, name=None, description=None, is_public=False, admin_only=False, slow_mode_seconds=0)
        group_large = Chat(id=None, created_by=1, type=ChatType.GROUP, member_count=chat_config.FAN_OUT_WRITE_THRESHOLD + 1, permissions={}, name=None, description=None, is_public=False, admin_only=False, slow_mode_seconds=0)
        supergroup = Chat(id=None, created_by=1, type=ChatType.SUPERGROUP, member_count=10, permissions={}, name=None, description=None, is_public=False, admin_only=False, slow_mode_seconds=0)
        channel = Chat(id=None, created_by=1, type=ChatType.CHANNEL, member_count=10, permissions={}, name=None, description=None, is_public=False, admin_only=False, slow_mode_seconds=0)

        assert direct.fanout_strategy == ChatFanoutStrategy.FANOUT_ON_WRITE
        assert group_small.fanout_strategy == ChatFanoutStrategy.FANOUT_ON_WRITE
        assert group_large.fanout_strategy == ChatFanoutStrategy.ACTIVE_SUBSCRIBERS
        assert supergroup.fanout_strategy == ChatFanoutStrategy.ACTIVE_SUBSCRIBERS
        assert channel.fanout_strategy == ChatFanoutStrategy.CHANNEL_SUBSCRIBERS

    def test_pull_events_clears_previous_events(self) -> None:
        chat = make_direct_chat()
        chat.pull_events()

        chat.update(
            updated_by=1,
            name="Foo",
            description="Bar",
            is_public=None,
            admin_only=None,
            slow_mode_seconds=None,
            permissions=None,
        )

        events = chat.pull_events()
        assert len(events) == 1
        assert chat.pull_events() == []




@pytest.mark.unit
@pytest.mark.chats
class TestChatPartialUpdate:
    """PATCH не должен затирать поля, которых нет в запросе."""

    def test_update_without_name_keeps_name_and_description(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2])
        chat.name = "Team"
        chat.description = "About the team"
        chat.pull_events()

        chat.update(
            updated_by=1,
            name=None,
            description=None,
            is_public=None,
            slow_mode_seconds=30,
        )

        assert chat.name == "Team"
        assert chat.description == "About the team"
        assert chat.slow_mode_seconds == 30

    def test_update_with_name_replaces_it(self) -> None:
        chat = make_group_chat(created_by=1, members_ids=[1, 2])
        chat.name = "Team"

        chat.update(updated_by=1, name="Squad", description=None, is_public=None)

        assert chat.name == "Squad"
