from datetime import timedelta
from uuid import uuid4

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.chats.ban_member import BanMemberCommand, BanMemberCommandHandler
from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
    NotFoundChatError,
)
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestBanMemberCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> BanMemberCommandHandler:
        return await request_container.get(BanMemberCommandHandler)

    async def test_owner_bans_member(
        self,
        handler: BanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
            )
        )

        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_banned is True

    async def test_ban_fires_banned_event(
        self,
        handler: BanMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
            )
        )

    async def test_ban_does_not_remove_from_chat(
        self,
        handler: BanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        original_count = group_chat.member_count

        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
            )
        )

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        assert chat.member_count == original_count

    async def test_owner_unbans_member(
        self,
        handler: BanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None

        member.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                banned_until=now_utc() - timedelta(days=1)
            )
        )

        refreshed = await chat_repository.get_member_chat(group_chat.id, 2)
        assert refreshed is not None
        assert refreshed.is_banned is False

    async def test_unban_fires_event_with_ban_false(
        self,
        handler: BanMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        chat_repository: ChatRepository,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None

        member.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                banned_until=now_utc() - timedelta(days=1)
            )
        )

    async def test_ban_then_unban_restores_access(
        self,
        handler: BanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            BanMemberCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2)
        )
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_banned is True

        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id, target_user_id=2,
                banned_until=now_utc() - timedelta(days=1))
        )
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_banned is False

    async def test_unban_already_active_member_is_noop(
        self,
        handler: BanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_banned is False

        await handler.handle(
            BanMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                banned_until=now_utc() - timedelta(days=1)
            )
        )

        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_banned is False

    async def test_ban_twice_is_idempotent(
        self,
        handler: BanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            BanMemberCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2)
        )
        await handler.handle(
            BanMemberCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2)
        )
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_banned is True

    async def test_regular_member_cannot_ban(
        self,
        handler: BanMemberCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        member_jwt = make_user_jwt(id="2")
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                BanMemberCommand(user_jwt_data=member_jwt, chat_id=group_chat.id, target_user_id=3)
            )

    async def test_cannot_ban_self(
        self,
        handler: BanMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                BanMemberCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    target_user_id=int(user_jwt.id),
                )
            )

    async def test_cannot_ban_nonexistent_member(
        self,
        handler: BanMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await handler.handle(
                BanMemberCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=9999)
            )

    async def test_ban_in_nonexistent_chat_raises(
        self,
        handler: BanMemberCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                BanMemberCommand(user_jwt_data=user_jwt, chat_id=uuid4(), target_user_id=2)
            )
