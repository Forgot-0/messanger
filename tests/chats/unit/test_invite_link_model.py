from datetime import timedelta
from uuid import uuid7

import pytest

from app.chats.exceptions import InvalidInviteLinkError, InviteLinkInactiveReason
from app.chats.models.invite import ChatInviteLink
from app.core.utils import now_utc


@pytest.mark.unit
@pytest.mark.chats
class TestChatInviteLink:
    def test_new_link_is_active_and_has_unique_code(self) -> None:
        first = ChatInviteLink.create(chat_id=uuid7(), created_by=1, name="  friends ")
        second = ChatInviteLink.create(chat_id=uuid7(), created_by=1)

        assert first.is_active
        assert first.name == "friends"
        assert first.code != second.code
        assert len(first.code) >= 16

    def test_expires_at_in_past_is_rejected(self) -> None:
        with pytest.raises(InvalidInviteLinkError) as exc:
            ChatInviteLink.create(chat_id=uuid7(), created_by=1, expires_at=now_utc() - timedelta(seconds=1))
        assert exc.value.reason == "expires_at_in_past"

    @pytest.mark.parametrize("usage_limit", [0, 100_000])
    def test_usage_limit_out_of_range_is_rejected(self, usage_limit: int) -> None:
        with pytest.raises(InvalidInviteLinkError):
            ChatInviteLink.create(chat_id=uuid7(), created_by=1, usage_limit=usage_limit)

    def test_inactive_reasons(self) -> None:
        link = ChatInviteLink.create(chat_id=uuid7(), created_by=1, usage_limit=1)

        link.usage_count = 1
        assert link.inactive_reason == InviteLinkInactiveReason.USAGE_LIMIT_REACHED

        link.expires_at = now_utc() - timedelta(minutes=1)
        assert link.inactive_reason == InviteLinkInactiveReason.EXPIRED

        link.revoke()
        assert link.inactive_reason == InviteLinkInactiveReason.REVOKED
        assert not link.is_active

    def test_revoke_is_idempotent(self) -> None:
        link = ChatInviteLink.create(chat_id=uuid7(), created_by=1)
        link.revoke()
        revoked_at = link.revoked_at

        link.revoke()

        assert link.revoked_at == revoked_at
