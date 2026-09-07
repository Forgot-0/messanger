from datetime import timedelta
from uuid import uuid4

import pytest

from app.chats.config import chat_config
from app.chats.models.chat_members import PERMANENT_UNTIL, ChatMember
from app.chats.models.chat_roles import ChatRole
from app.chats.models.permission import (
    MEMBER_PERMISSIONS,
    OWNER_PERMISSIONS,
    ChatRolesEnum,
)
from app.core.utils import now_utc


def make_member(
    role: ChatRole,
    *,
    is_banned: bool = False,
    is_muted: bool = False,
    overrides: dict | None = None,
) -> ChatMember:
    m = ChatMember()
    m.user_id = 1
    m.chat_id = uuid4()
    m.role_id = role.id
    m.permissions_overrides = overrides or {}
    m.role = role
    if is_banned:
        m.ban(0)
    if is_muted:
        m.muted_until = now_utc() + timedelta(days=1)
    return m


OWNER  = ChatRolesEnum.OWNER.value
ADMIN  = ChatRolesEnum.ADMIN.value
EDITOR = ChatRolesEnum.EDITOR.value
DIRECT = ChatRolesEnum.DIRECT_MEMBER.value
MEMBER = ChatRolesEnum.MEMBER.value
VIEWER = ChatRolesEnum.VIEWER.value


@pytest.mark.unit
@pytest.mark.chats
class TestEffectivePermissions:

    def test_returns_role_permissions_without_overrides(self) -> None:
        member = make_member(OWNER)
        perms = member.effective_permissions()
        assert perms == OWNER_PERMISSIONS

    def test_override_grants_extra_permission(self) -> None:
        member = make_member(MEMBER, overrides={"message:delete": True})
        perms = member.effective_permissions()
        assert perms["message:delete"] is True

    def test_override_revokes_existing_permission(self) -> None:
        member = make_member(OWNER, overrides={"chat:delete": False})
        perms = member.effective_permissions()
        assert perms["chat:delete"] is False

    def test_overrides_do_not_mutate_role_permissions(self) -> None:
        member = make_member(OWNER, overrides={"chat:delete": False})
        member.effective_permissions()
        assert OWNER.permissions["chat:delete"] is True

    def test_empty_overrides_returns_role_permissions(self) -> None:
        member = make_member(MEMBER, overrides={})
        assert member.effective_permissions() == MEMBER_PERMISSIONS

    def test_multiple_overrides_all_applied(self) -> None:
        overrides = {"message:delete": True, "member:kick": True, "chat:delete": False}
        member = make_member(MEMBER, overrides=overrides)
        perms = member.effective_permissions()
        assert perms["message:delete"] is True
        assert perms["member:kick"] is True
        assert perms["chat:delete"] is False

    def test_viewer_with_send_override(self) -> None:
        member = make_member(VIEWER, overrides={"message:send": True})
        perms = member.effective_permissions()
        assert perms["message:send"] is True
        assert perms["message:delete"] is False


@pytest.mark.unit
@pytest.mark.chats
class TestHasPermission:

    def test_owner_has_chat_delete(self) -> None:
        assert make_member(OWNER).has_permission("chat:delete") is True

    def test_member_does_not_have_chat_delete(self) -> None:
        assert make_member(MEMBER).has_permission("chat:delete") is False

    def test_override_takes_precedence_over_role(self) -> None:
        member = make_member(VIEWER, overrides={"message:send": True})
        assert member.has_permission("message:send") is True

    def test_override_false_overrides_role_true(self) -> None:
        member = make_member(OWNER, overrides={"chat:delete": False})
        assert member.has_permission("chat:delete") is False

    def test_unknown_permission_returns_false(self) -> None:
        assert make_member(OWNER).has_permission("nonexistent:perm") is False

@pytest.mark.unit
@pytest.mark.chats
class TestStaffFlags:

    @pytest.mark.parametrize("role,expected", [
        (OWNER,  True),
        (ADMIN,  True),
        (EDITOR, True),
        (DIRECT, False),
        (MEMBER, False),
        (VIEWER, False),
    ])
    def test_is_staff(self, role: ChatRole, expected: bool) -> None:
        assert make_member(role).is_staff is expected

    @pytest.mark.parametrize("role,expected", [
        (OWNER,  True),
        (ADMIN,  True),
        (EDITOR, True),
        (DIRECT, False),
        (MEMBER, False),
        (VIEWER, False),
    ])
    def test_is_editor_or_above(self, role: ChatRole, expected: bool) -> None:
        assert make_member(role).is_editor_or_above is expected

    def test_staff_threshold_is_config_driven(self) -> None:
        custom_role = ChatRole(id=99, name="custom", level=chat_config.CHAT_STAFF_MIN_ROLE_LEVEL)
        assert make_member(custom_role).is_staff is True

    def test_just_below_staff_threshold_is_not_staff(self) -> None:
        custom_role = ChatRole(id=99, name="custom", level=chat_config.CHAT_STAFF_MIN_ROLE_LEVEL - 1)
        assert make_member(custom_role).is_staff is False


@pytest.mark.unit
@pytest.mark.chats
class TestChannelFlags:

    @pytest.mark.parametrize("role,expected", [
        (OWNER,  True),
        (ADMIN,  True),
        (EDITOR, True),
        (DIRECT, False),
        (MEMBER, False),
        (VIEWER, False),
    ])
    def test_is_channel_staff(self, role: ChatRole, expected: bool) -> None:
        assert make_member(role).is_channel_staff is expected

    def test_viewer_is_channel_subscriber(self) -> None:
        assert make_member(VIEWER).is_channel_subscriber is True

    @pytest.mark.parametrize("role", [OWNER, ADMIN, EDITOR, DIRECT, MEMBER])
    def test_non_viewer_is_not_channel_subscriber(self, role: ChatRole) -> None:
        assert make_member(role).is_channel_subscriber is False


@pytest.mark.unit
@pytest.mark.chats
class TestCanBypassSlowMode:

    def test_owner_bypasses_slow_mode(self) -> None:
        assert make_member(OWNER).can_bypass_slow_mode() is True

    def test_admin_bypasses_slow_mode(self) -> None:
        assert make_member(ADMIN).can_bypass_slow_mode() is True

    def test_editor_bypasses_slow_mode(self) -> None:
        assert make_member(EDITOR).can_bypass_slow_mode() is True

    def test_regular_member_does_not_bypass(self) -> None:
        assert make_member(MEMBER).can_bypass_slow_mode() is False

    def test_viewer_does_not_bypass(self) -> None:
        assert make_member(VIEWER).can_bypass_slow_mode() is False

    def test_member_with_bypass_override_can_bypass(self) -> None:
        member = make_member(MEMBER, overrides={"slowmode:bypass": True})
        assert member.can_bypass_slow_mode() is True

    def test_owner_with_bypass_revoked_still_bypasses_via_staff(self) -> None:
        member = make_member(OWNER, overrides={"slowmode:bypass": False})
        assert member.can_bypass_slow_mode() is True



@pytest.mark.unit
@pytest.mark.chats
class TestBanMuteSemantics:
    """NULL = ограничения нет; «навсегда» — явный маркер в будущем."""

    def test_fresh_member_is_neither_banned_nor_muted(self) -> None:
        member = ChatMember.create(chat_id=uuid4(), user_id=1, role_id=MEMBER.id)

        assert member.banned_until is None
        assert member.is_banned is False
        assert member.is_muted is False

    def test_bare_constructor_is_not_banned_either(self) -> None:
        # Раньше строка, созданная мимо create(), рождалась забаненной навсегда.
        assert ChatMember().is_banned is False

    def test_ban_without_deadline_is_permanent(self) -> None:
        member = ChatMember.create(chat_id=uuid4(), user_id=1, role_id=MEMBER.id)
        member.ban(banned_by=2)

        assert member.banned_until == PERMANENT_UNTIL
        assert member.is_banned is True

    def test_ban_with_future_deadline_is_temporary(self) -> None:
        member = ChatMember.create(chat_id=uuid4(), user_id=1, role_id=MEMBER.id)
        until = now_utc() + timedelta(hours=1)
        member.ban(banned_by=2, banned_until=until)

        assert member.banned_until == until
        assert member.is_banned is True

    def test_past_deadline_lifts_the_ban(self) -> None:
        member = ChatMember.create(chat_id=uuid4(), user_id=1, role_id=MEMBER.id)
        member.ban(banned_by=2)
        member.ban(banned_by=2, banned_until=now_utc() - timedelta(days=1))

        assert member.banned_until is None
        assert member.is_banned is False

    def test_mute_mirrors_ban_semantics(self) -> None:
        member = ChatMember.create(chat_id=uuid4(), user_id=1, role_id=MEMBER.id)

        member.mute()
        assert member.is_muted is True

        member.mute(muted_until=now_utc() - timedelta(minutes=1))
        assert member.muted_until is None
        assert member.is_muted is False
