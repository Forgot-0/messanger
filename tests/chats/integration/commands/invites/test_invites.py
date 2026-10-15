from datetime import timedelta

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.invites.create import CreateInviteLinkCommand, CreateInviteLinkCommandHandler
from app.chats.commands.invites.join import JoinChatByInviteCommand, JoinChatByInviteCommandHandler
from app.chats.commands.invites.revoke import RevokeInviteLinkCommand, RevokeInviteLinkCommandHandler
from app.chats.dtos.invites import ChatInviteLinkDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    AlreadyMemberError,
    InvalidInviteLinkError,
    InviteLinkExpiredError,
    InviteLinkInactiveReason,
    NotFoundInviteLinkError,
)
from app.chats.models.chat import AddedChatMemberEvent, Chat, ChatType
from app.chats.models.chat_roles import ChatRoleId
from app.chats.queries.invites.get_list import GetInviteLinksQuery, GetInviteLinksQueryHandler
from app.chats.queries.invites.preview import GetInvitePreviewQuery, GetInvitePreviewQueryHandler
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from tests.mocks import RecordingEventBus


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestInviteLinks:

    @pytest.fixture
    async def create(self, request_container: AsyncContainer, user_jwt: UserJWTData):
        handler = await request_container.get(CreateInviteLinkCommandHandler)

        async def _create(chat: Chat, **kwargs) -> ChatInviteLinkDTO:
            return await handler.handle(
                CreateInviteLinkCommand(user_jwt_data=user_jwt, chat_id=chat.id, **kwargs)
            )

        return _create

    @pytest.fixture
    async def join(self, request_container: AsyncContainer) -> JoinChatByInviteCommandHandler:
        return await request_container.get(JoinChatByInviteCommandHandler)

    async def test_create_and_list(
        self,
        create,
        request_container: AsyncContainer,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        first = await create(group_chat, name="team", usage_limit=5)
        second = await create(group_chat)

        handler = await request_container.get(GetInviteLinksQueryHandler)
        page = await handler.handle(GetInviteLinksQuery(user_jwt_data=user_jwt, chat_id=group_chat.id, limit=1))
        assert page.has_next is True
        assert [invite.id for invite in page.invites] == [second.id]

        rest = await handler.handle(GetInviteLinksQuery(
            user_jwt_data=user_jwt, chat_id=group_chat.id, limit=1, last_invite_id=page.next_invite_id,
        ))
        assert [invite.id for invite in rest.invites] == [first.id]
        assert rest.invites[0].name == "team"
        assert rest.invites[0].usage_limit == 5
        assert rest.invites[0].is_active is True

    async def test_regular_member_cannot_create(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        handler = await request_container.get(CreateInviteLinkCommandHandler)

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(CreateInviteLinkCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id,
            ))

    async def test_direct_chat_has_no_invites(self, create, direct_chat: Chat) -> None:
        with pytest.raises((InvalidInviteLinkError, AccessDeniedChatError)):
            await create(direct_chat)

    async def test_join_private_group_by_link(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        make_user_jwt,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        invite = await create(group_chat)
        count_before = group_chat.member_count

        dto = await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="42"), code=invite.code))

        assert dto.id == group_chat.id
        member = await chat_repository.get_member_chat(group_chat.id, 42)
        assert member is not None and member.role_id == ChatRoleId.MEMBER
        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None and chat.member_count == count_before + 1
        joined = [e for e in mock_event_bus.of_type(AddedChatMemberEvent) if e.user_id == 42]
        assert len(joined) == 1
        assert joined[0].role_id == ChatRoleId.MEMBER

    async def test_join_channel_as_viewer(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        channel = Chat.create(created_by=int(user_jwt.id), members_ids=[], chat_type=ChatType.CHANNEL, name="News")
        db_session.add(channel)
        await db_session.commit()
        invite = await create(channel)

        await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="43"), code=invite.code))

        member = await chat_repository.get_member_chat(channel.id, 43)
        assert member is not None and member.role_id == ChatRoleId.VIEWER

    async def test_usage_limit(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        invite_repository: ChatInviteLinkRepository,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await create(group_chat, usage_limit=1)
        await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="50"), code=invite.code))

        with pytest.raises(InviteLinkExpiredError) as exc:
            await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="51"), code=invite.code))

        assert exc.value.reason == InviteLinkInactiveReason.USAGE_LIMIT_REACHED
        stored = await invite_repository.get_by_id(invite.id)
        assert stored is not None and stored.usage_count == 1

    async def test_expired_link(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        invite_repository: ChatInviteLinkRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await create(group_chat, expires_at=now_utc() + timedelta(hours=1))
        stored = await invite_repository.get_by_id(invite.id)
        assert stored is not None
        stored.expires_at = now_utc() - timedelta(seconds=1)
        await db_session.commit()

        with pytest.raises(InviteLinkExpiredError) as exc:
            await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="52"), code=invite.code))
        assert exc.value.reason == InviteLinkInactiveReason.EXPIRED

    async def test_revoked_link(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        request_container: AsyncContainer,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await create(group_chat)
        revoke = await request_container.get(RevokeInviteLinkCommandHandler)
        revoked = await revoke.handle(RevokeInviteLinkCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, invite_id=invite.id,
        ))
        assert revoked.is_revoked is True and revoked.is_active is False

        with pytest.raises(InviteLinkExpiredError) as exc:
            await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="53"), code=invite.code))
        assert exc.value.reason == InviteLinkInactiveReason.REVOKED

    async def test_unknown_code(self, join: JoinChatByInviteCommandHandler, make_user_jwt) -> None:
        with pytest.raises(NotFoundInviteLinkError):
            await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="54"), code="nope"))

    async def test_existing_member_gets_conflict_and_usage_is_not_spent(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        invite_repository: ChatInviteLinkRepository,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await create(group_chat, usage_limit=1)

        with pytest.raises(AlreadyMemberError):
            await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="2"), code=invite.code))

        stored = await invite_repository.get_by_id(invite.id)
        assert stored is not None and stored.usage_count == 0

    async def test_banned_member_cannot_rejoin_by_link(
        self,
        create,
        join: JoinChatByInviteCommandHandler,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await create(group_chat)
        member = await chat_repository.get_member_chat(group_chat.id, 3)
        assert member is not None
        member.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        with pytest.raises(AccessDeniedChatError):
            await join.handle(JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="3"), code=invite.code))

    async def test_preview_before_joining(
        self,
        create,
        request_container: AsyncContainer,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await create(group_chat, expires_at=now_utc() + timedelta(days=1))
        handler = await request_container.get(GetInvitePreviewQueryHandler)

        outsider = await handler.handle(GetInvitePreviewQuery(user_jwt_data=make_user_jwt(id="60"), code=invite.code))
        member = await handler.handle(GetInvitePreviewQuery(user_jwt_data=make_user_jwt(id="2"), code=invite.code))

        assert outsider.chat.id == group_chat.id
        assert outsider.chat.name == group_chat.name
        assert outsider.chat.member_count == group_chat.member_count
        assert outsider.chat.is_member is False
        assert outsider.expires_at == invite.expires_at
        assert member.chat.is_member is True
