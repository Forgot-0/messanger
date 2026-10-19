from datetime import timedelta

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.chats.join import JoinChatCommand, JoinChatCommandHandler
from app.chats.commands.invites.create import CreateInviteLinkCommand, CreateInviteLinkCommandHandler
from app.chats.commands.invites.join import JoinChatByInviteCommand, JoinChatByInviteCommandHandler
from app.chats.commands.join_requests.approve import (
    ApproveJoinRequestCommand,
    ApproveJoinRequestCommandHandler,
)
from app.chats.commands.join_requests.cancel import (
    CancelJoinRequestCommand,
    CancelJoinRequestCommandHandler,
)
from app.chats.commands.join_requests.decline import (
    DeclineJoinRequestCommand,
    DeclineJoinRequestCommandHandler,
)
from app.chats.config import chat_config
from app.chats.dtos.invites import ChatInviteLinkDTO
from app.chats.dtos.join_requests import JoinResultStatus
from app.chats.exceptions import (
    AccessDeniedChatError,
    AlreadyMemberError,
    InvalidInviteLinkError,
    JoinRequestNotPendingError,
    JoinRequestPendingError,
    JoinRequestRetryLaterError,
    NotFoundJoinRequestError,
)
from app.chats.models.chat import AddedChatMemberEvent, Chat, ChatType
from app.chats.models.chat_roles import ChatRoleId
from app.chats.models.join_request import (
    ApprovedChatJoinRequestEvent,
    CancelledChatJoinRequestEvent,
    CreatedChatJoinRequestEvent,
    DeclinedChatJoinRequestEvent,
    JoinRequestStatus,
)
from app.chats.models.profile import ChatUserProfile
from app.chats.queries.join_requests.get_list import (
    GetJoinRequestsQuery,
    GetJoinRequestsQueryHandler,
)
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from tests.mocks import RecordingEventBus


@pytest.fixture
def join_request_repository(db_session: AsyncSession) -> ChatJoinRequestRepository:
    return ChatJoinRequestRepository(session=db_session)


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatJoinRequests:

    @pytest.fixture
    async def request_link(self, request_container: AsyncContainer, user_jwt: UserJWTData):
        handler = await request_container.get(CreateInviteLinkCommandHandler)

        async def _create(chat: Chat, **kwargs) -> ChatInviteLinkDTO:
            return await handler.handle(
                CreateInviteLinkCommand(
                    user_jwt_data=user_jwt,
                    chat_id=chat.id,
                    creates_join_request=True,
                    **kwargs,
                )
            )

        return _create

    @pytest.fixture
    async def join_by_link(self, request_container: AsyncContainer) -> JoinChatByInviteCommandHandler:
        return await request_container.get(JoinChatByInviteCommandHandler)

    @pytest.fixture
    async def approve(self, request_container: AsyncContainer) -> ApproveJoinRequestCommandHandler:
        return await request_container.get(ApproveJoinRequestCommandHandler)

    @pytest.fixture
    async def decline(self, request_container: AsyncContainer) -> DeclineJoinRequestCommandHandler:
        return await request_container.get(DeclineJoinRequestCommandHandler)

    async def test_request_link_does_not_let_user_in(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        join_request_repository: ChatJoinRequestRepository,
        invite_repository: ChatInviteLinkRepository,
        chat_repository: ChatRepository,
        group_chat: Chat,
        make_user_jwt,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        invite = await request_link(group_chat, name="by request")
        count_before = group_chat.member_count

        result = await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="42"), code=invite.code)
        )

        assert result.status == JoinResultStatus.REQUESTED
        assert result.chat is None
        assert result.join_request is not None
        assert result.join_request.status == JoinRequestStatus.PENDING
        assert result.join_request.invite_link_id == invite.id

        assert await chat_repository.get_member_chat(group_chat.id, 42) is None
        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None and chat.member_count == count_before

        stored_link = await invite_repository.get_by_id(invite.id)
        assert stored_link is not None and stored_link.usage_count == 0

        stored = await join_request_repository.get(group_chat.id, 42)
        assert stored is not None and stored.is_pending is True

        created = [e for e in mock_event_bus.of_type(CreatedChatJoinRequestEvent) if e.user_id == 42]
        assert len(created) == 1
        assert created[0].invite_link_id == str(invite.id)

    async def test_request_link_cannot_have_usage_limit(
        self,
        request_link,
        group_chat: Chat,
    ) -> None:
        with pytest.raises(InvalidInviteLinkError) as exc:
            await request_link(group_chat, usage_limit=10)
        assert exc.value.reason == "request_link_with_usage_limit"

    async def test_member_gets_conflict_instead_of_request(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)

        with pytest.raises(AlreadyMemberError):
            await join_by_link.handle(
                JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="2"), code=invite.code)
            )

    async def test_second_request_is_rejected_while_pending(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        applicant = make_user_jwt(id="43")

        await join_by_link.handle(JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code))

        with pytest.raises(JoinRequestPendingError):
            await join_by_link.handle(
                JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code)
            )

    async def test_approve_adds_member_and_credits_the_link(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        approve: ApproveJoinRequestCommandHandler,
        join_request_repository: ChatJoinRequestRepository,
        invite_repository: ChatInviteLinkRepository,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        invite = await request_link(group_chat)
        count_before = group_chat.member_count
        await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="44"), code=invite.code)
        )

        await approve.handle(
            ApproveJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=44
            )
        )

        member = await chat_repository.get_member_chat(group_chat.id, 44)
        assert member is not None and member.role_id == ChatRoleId.MEMBER

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None and chat.member_count == count_before + 1

        stored_link = await invite_repository.get_by_id(invite.id)
        assert stored_link is not None and stored_link.usage_count == 1

        stored = await join_request_repository.get(group_chat.id, 44)
        assert stored is not None
        assert stored.status == JoinRequestStatus.APPROVED
        assert stored.resolved_by == int(user_jwt.id)

        approved = [e for e in mock_event_bus.of_type(ApprovedChatJoinRequestEvent) if e.user_id == 44]
        assert len(approved) == 1
        assert approved[0].role_id == int(ChatRoleId.MEMBER)
        assert [e for e in mock_event_bus.of_type(AddedChatMemberEvent) if e.user_id == 44]

    async def test_channel_applicant_becomes_viewer(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        approve: ApproveJoinRequestCommandHandler,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        channel = Chat.create(
            created_by=int(user_jwt.id), members_ids=[], chat_type=ChatType.CHANNEL, name="News"
        )
        db_session.add(channel)
        await db_session.commit()

        invite = await request_link(channel)
        await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="45"), code=invite.code)
        )
        await approve.handle(
            ApproveJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=channel.id, target_user_id=45
            )
        )

        member = await chat_repository.get_member_chat(channel.id, 45)
        assert member is not None and member.role_id == ChatRoleId.VIEWER

    async def test_resolved_request_cannot_be_resolved_twice(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        approve: ApproveJoinRequestCommandHandler,
        decline: DeclineJoinRequestCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="46"), code=invite.code)
        )
        await approve.handle(
            ApproveJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=46
            )
        )

        with pytest.raises(JoinRequestNotPendingError) as exc:
            await approve.handle(
                ApproveJoinRequestCommand(
                    user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=46
                )
            )
        assert exc.value.status_value == JoinRequestStatus.APPROVED.value

        with pytest.raises(JoinRequestNotPendingError):
            await decline.handle(
                DeclineJoinRequestCommand(
                    user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=46
                )
            )

    async def test_decline_keeps_user_out_and_blocks_retry(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        decline: DeclineJoinRequestCommandHandler,
        join_request_repository: ChatJoinRequestRepository,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        invite = await request_link(group_chat)
        applicant = make_user_jwt(id="47")
        await join_by_link.handle(JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code))

        await decline.handle(
            DeclineJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=47
            )
        )

        assert await chat_repository.get_member_chat(group_chat.id, 47) is None
        stored = await join_request_repository.get(group_chat.id, 47)
        assert stored is not None and stored.status == JoinRequestStatus.DECLINED
        assert [e for e in mock_event_bus.of_type(DeclinedChatJoinRequestEvent) if e.user_id == 47]

        with pytest.raises(JoinRequestRetryLaterError):
            await join_by_link.handle(
                JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code)
            )

    async def test_regular_member_cannot_moderate_requests(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        approve: ApproveJoinRequestCommandHandler,
        decline: DeclineJoinRequestCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="48"), code=invite.code)
        )
        member_jwt = make_user_jwt(id="2")

        with pytest.raises(AccessDeniedChatError):
            await approve.handle(
                ApproveJoinRequestCommand(
                    user_jwt_data=member_jwt, chat_id=group_chat.id, target_user_id=48
                )
            )

        with pytest.raises(AccessDeniedChatError):
            await decline.handle(
                DeclineJoinRequestCommand(
                    user_jwt_data=member_jwt, chat_id=group_chat.id, target_user_id=48
                )
            )

    async def test_applicant_cancels_own_request(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        request_container: AsyncContainer,
        join_request_repository: ChatJoinRequestRepository,
        group_chat: Chat,
        make_user_jwt,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        invite = await request_link(group_chat)
        applicant = make_user_jwt(id="49")
        await join_by_link.handle(JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code))

        cancel = await request_container.get(CancelJoinRequestCommandHandler)
        await cancel.handle(CancelJoinRequestCommand(user_jwt_data=applicant, chat_id=group_chat.id))

        assert await join_request_repository.get(group_chat.id, 49) is None
        assert [e for e in mock_event_bus.of_type(CancelledChatJoinRequestEvent) if e.user_id == 49]

        with pytest.raises(NotFoundJoinRequestError):
            await cancel.handle(
                CancelJoinRequestCommand(user_jwt_data=applicant, chat_id=group_chat.id)
            )

    async def test_public_chat_with_join_by_request_creates_request(
        self,
        request_container: AsyncContainer,
        join_request_repository: ChatJoinRequestRepository,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        chat = Chat.create(
            created_by=int(user_jwt.id),
            members_ids=[],
            chat_type=ChatType.GROUP,
            name="Open but curated",
            is_public=True,
            join_by_request=True,
        )
        db_session.add(chat)
        await db_session.commit()

        handler = await request_container.get(JoinChatCommandHandler)
        result = await handler.handle(
            JoinChatCommand(user_jwt_data=make_user_jwt(id="50"), chat_id=chat.id)
        )

        assert result.status == JoinResultStatus.REQUESTED
        assert await chat_repository.get_member_chat(chat.id, 50) is None
        stored = await join_request_repository.get(chat.id, 50)
        assert stored is not None and stored.invite_link_id is None

    async def test_public_chat_without_flag_joins_instantly(
        self,
        request_container: AsyncContainer,
        chat_repository: ChatRepository,
        public_group_chat: Chat,
        make_user_jwt,
    ) -> None:
        handler = await request_container.get(JoinChatCommandHandler)

        result = await handler.handle(
            JoinChatCommand(user_jwt_data=make_user_jwt(id="51"), chat_id=public_group_chat.id)
        )

        assert result.status == JoinResultStatus.JOINED
        assert result.chat is not None and result.chat.id == public_group_chat.id
        assert await chat_repository.get_member_chat(public_group_chat.id, 51) is not None

    async def test_pending_list_is_paginated_and_carries_profiles(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        request_container: AsyncContainer,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        db_session.add(ChatUserProfile.create(user_id=52, username="first"))
        db_session.add(ChatUserProfile.create(user_id=53, username="second"))
        await db_session.commit()

        for user_id in (52, 53):
            await join_by_link.handle(
                JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id=str(user_id)), code=invite.code)
            )

        handler = await request_container.get(GetJoinRequestsQueryHandler)
        first_page = await handler.handle(
            GetJoinRequestsQuery(user_jwt_data=user_jwt, chat_id=group_chat.id, limit=1)
        )

        assert first_page.total == 2
        assert first_page.has_next is True
        assert [item.user_id for item in first_page.requests] == [53]
        assert first_page.requests[0].profile is not None
        assert first_page.requests[0].profile.username == "second"

        second_page = await handler.handle(
            GetJoinRequestsQuery(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                limit=1,
                last_requested_at=first_page.next_requested_at,
                last_user_id=first_page.next_user_id,
            )
        )

        assert [item.user_id for item in second_page.requests] == [52]
        assert second_page.has_next is False

    async def test_resolved_requests_leave_the_pending_list(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        approve: ApproveJoinRequestCommandHandler,
        request_container: AsyncContainer,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="54"), code=invite.code)
        )
        await approve.handle(
            ApproveJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=54
            )
        )

        handler = await request_container.get(GetJoinRequestsQueryHandler)
        page = await handler.handle(
            GetJoinRequestsQuery(user_jwt_data=user_jwt, chat_id=group_chat.id)
        )

        assert page.total == 0
        assert page.requests == []

    async def test_member_cannot_read_pending_list(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        handler = await request_container.get(GetJoinRequestsQueryHandler)

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                GetJoinRequestsQuery(
                    user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id
                )
            )

    async def test_banned_user_cannot_request(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        member = await chat_repository.get_member_chat(group_chat.id, 3)
        assert member is not None
        member.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        with pytest.raises(AccessDeniedChatError):
            await join_by_link.handle(
                JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="3"), code=invite.code)
            )

    async def test_unknown_request_cannot_be_approved(
        self,
        approve: ApproveJoinRequestCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundJoinRequestError):
            await approve.handle(
                ApproveJoinRequestCommand(
                    user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=999
                )
            )

    async def test_approve_closes_request_of_already_added_member(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        approve: ApproveJoinRequestCommandHandler,
        join_request_repository: ChatJoinRequestRepository,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=make_user_jwt(id="56"), code=invite.code)
        )
        # владелец добавил человека руками, пока заявка висела
        group_chat.add_member(56, role_id=ChatRoleId.MEMBER)
        group_chat.pull_events()
        await db_session.commit()
        count_before = group_chat.member_count

        await approve.handle(
            ApproveJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=56
            )
        )

        stored = await join_request_repository.get(group_chat.id, 56)
        assert stored is not None and stored.status == JoinRequestStatus.APPROVED
        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None and chat.member_count == count_before

    async def test_declined_request_is_renewed_after_cooldown(
        self,
        request_link,
        join_by_link: JoinChatByInviteCommandHandler,
        decline: DeclineJoinRequestCommandHandler,
        join_request_repository: ChatJoinRequestRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        invite = await request_link(group_chat)
        applicant = make_user_jwt(id="55")
        await join_by_link.handle(JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code))
        await decline.handle(
            DeclineJoinRequestCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=55
            )
        )

        declined = await join_request_repository.get(group_chat.id, 55)
        assert declined is not None
        declined.resolved_at = now_utc() - timedelta(
            seconds=chat_config.JOIN_REQUEST_RETRY_AFTER_SECONDS + 1
        )
        await db_session.commit()

        result = await join_by_link.handle(
            JoinChatByInviteCommand(user_jwt_data=applicant, code=invite.code)
        )

        assert result.status == JoinResultStatus.REQUESTED
        renewed = await join_request_repository.get(group_chat.id, 55)
        assert renewed is not None
        assert renewed.is_pending is True
        assert renewed.resolved_by is None
