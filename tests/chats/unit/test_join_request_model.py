from datetime import timedelta
from uuid import uuid7

import pytest

from app.chats.config import chat_config
from app.chats.exceptions import (
    JoinRequestNotAllowedError,
    JoinRequestPendingError,
    JoinRequestRetryLaterError,
)
from app.chats.models.chat import Chat, ChatType
from app.chats.models.chat_roles import ChatRoleId
from app.chats.models.join_request import (
    ApprovedChatJoinRequestsEvent,
    CancelledChatJoinRequestEvent,
    ChatJoinRequest,
    CreatedChatJoinRequestEvent,
    DeclinedChatJoinRequestsEvent,
    JoinRequestStatus,
)
from app.core.utils import now_utc


@pytest.mark.unit
@pytest.mark.chats
class TestChatJoinRequest:
    def test_new_request_is_pending_and_registers_event(self) -> None:
        chat_id, link_id = uuid7(), uuid7()

        request = ChatJoinRequest.create(chat_id=chat_id, user_id=42, invite_link_id=link_id)

        assert request.status == JoinRequestStatus.PENDING
        assert request.is_pending is True
        assert request.resolved_at is None

        events = request.pull_events()
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, CreatedChatJoinRequestEvent)
        assert event.get_name() == "chats.join_request.created"
        assert event.user_id == 42
        assert event.invite_link_id == str(link_id)
        assert event.get_partition_key() == str(chat_id)

    def test_approve_resolves_row_and_leaves_the_event_to_the_chat(self) -> None:
        request = ChatJoinRequest.create(chat_id=uuid7(), user_id=42)
        request.pull_events()

        request.approve(resolved_by=1)

        assert request.status == JoinRequestStatus.APPROVED
        assert request.is_pending is False
        assert request.resolved_by == 1
        assert request.retry_at is None
        # событие — одно на весь пакет, его регистрирует Chat
        assert request.pull_events() == []

    def test_decline_blocks_retry_until_cooldown_passes(self) -> None:
        request = ChatJoinRequest.create(chat_id=uuid7(), user_id=42)
        request.pull_events()

        request.decline(resolved_by=1)

        assert request.status == JoinRequestStatus.DECLINED
        assert request.pull_events() == []

        with pytest.raises(JoinRequestRetryLaterError) as exc:
            request.renew()
        assert 0 < exc.value.retry_after <= chat_config.JOIN_REQUEST_RETRY_AFTER_SECONDS + 1

        request.resolved_at = now_utc() - timedelta(
            seconds=chat_config.JOIN_REQUEST_RETRY_AFTER_SECONDS + 1
        )
        request.renew()

        assert request.is_pending is True
        assert request.resolved_by is None
        assert isinstance(request.pull_events()[0], CreatedChatJoinRequestEvent)

    def test_approved_request_can_be_renewed_without_cooldown(self) -> None:
        request = ChatJoinRequest.create(chat_id=uuid7(), user_id=42)
        request.approve(resolved_by=1)
        request.pull_events()

        request.renew(invite_link_id=None)

        assert request.is_pending is True
        assert request.status == JoinRequestStatus.PENDING

    def test_pending_request_cannot_be_renewed(self) -> None:
        request = ChatJoinRequest.create(chat_id=uuid7(), user_id=42)

        with pytest.raises(JoinRequestPendingError):
            request.renew()

    def test_cancel_registers_event(self) -> None:
        request = ChatJoinRequest.create(chat_id=uuid7(), user_id=42)
        request.pull_events()

        request.cancel()

        assert isinstance(request.pull_events()[0], CancelledChatJoinRequestEvent)


@pytest.mark.unit
@pytest.mark.chats
class TestChatJoinByRequestFlag:
    def test_group_can_be_created_with_join_by_request(self) -> None:
        chat = Chat.create(
            created_by=1, members_ids=[], chat_type=ChatType.GROUP, join_by_request=True
        )
        assert chat.join_by_request is True

    def test_direct_chat_never_asks_for_approval(self) -> None:
        chat = Chat.create(
            created_by=1, members_ids=[2], chat_type=ChatType.DIRECT, join_by_request=True
        )
        assert chat.join_by_request is False

        with pytest.raises(JoinRequestNotAllowedError):
            chat.set_join_by_request(True)

    def test_default_member_role_by_chat_type(self) -> None:
        assert Chat.default_member_role(ChatType.CHANNEL) == ChatRoleId.VIEWER
        assert Chat.default_member_role(ChatType.GROUP) == ChatRoleId.MEMBER
        assert Chat.default_member_role(ChatType.SUPERGROUP) == ChatRoleId.MEMBER
        assert Chat.default_member_role(ChatType.DIRECT) == ChatRoleId.DIRECT_MEMBER


@pytest.mark.unit
@pytest.mark.chats
class TestChatJoinRequestBatchEvents:
    def _chat(self) -> Chat:
        chat = Chat.create(created_by=1, members_ids=[], chat_type=ChatType.GROUP)
        chat.pull_events()
        return chat

    def test_approved_batch_is_one_event(self) -> None:
        chat = self._chat()

        chat.approve_join_requests([42, 43], resolved_by=1, role_id=ChatRoleId.MEMBER)

        events = chat.pull_events()
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ApprovedChatJoinRequestsEvent)
        assert event.get_name() == "chats.join_request.approved"
        assert event.user_ids == [42, 43]
        assert event.role_id == int(ChatRoleId.MEMBER)
        assert event.get_partition_key() == str(chat.id)

    def test_declined_batch_is_one_event(self) -> None:
        chat = self._chat()

        chat.decline_join_requests([42, 43], resolved_by=1)

        event = chat.pull_events()[0]
        assert isinstance(event, DeclinedChatJoinRequestsEvent)
        assert event.user_ids == [42, 43]
        assert event.count == 2
        assert event.all is False

    def test_decline_all_carries_the_count_without_the_list(self) -> None:
        chat = self._chat()

        chat.decline_join_requests([], resolved_by=1, count=5000, decline_all=True)

        event = chat.pull_events()[0]
        assert isinstance(event, DeclinedChatJoinRequestsEvent)
        assert event.all is True
        assert event.count == 5000
        assert event.user_ids == []

    def test_empty_batch_registers_nothing(self) -> None:
        chat = self._chat()

        chat.approve_join_requests([], resolved_by=1, role_id=ChatRoleId.MEMBER)
        chat.decline_join_requests([], resolved_by=1)

        assert chat.pull_events() == []
