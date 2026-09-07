from uuid import uuid4

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.chats.join import JoinChatCommand, JoinChatCommandHandler
from app.chats.exceptions import (
    AccessDeniedChatError,
    AlreadyMemberError,
    NotFoundChatError,
)
from app.chats.models.chat import Chat
from app.chats.models.permission import ChatRolesEnum
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestJoinChatCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> JoinChatCommandHandler:
        return await request_container.get(JoinChatCommandHandler)

    async def test_user_joins_public_group_and_gets_member_role(
        self,
        handler: JoinChatCommandHandler,
        public_group_chat: Chat,
        chat_repository: ChatRepository,
        make_user_jwt,
    ) -> None:
        newcomer = make_user_jwt(id="99")

        await handler.handle(JoinChatCommand(chat_id=public_group_chat.id, user_jwt_data=newcomer))

        member = await chat_repository.get_member_chat(chat_id=public_group_chat.id, member_id=99)
        assert member is not None
        assert member.role_id == ChatRolesEnum.MEMBER.value.id

    async def test_cannot_join_private_group(
        self,
        handler: JoinChatCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                JoinChatCommand(chat_id=group_chat.id, user_jwt_data=make_user_jwt(id="99"))
            )

    async def test_cannot_join_direct_chat(
        self,
        handler: JoinChatCommandHandler,
        direct_chat: Chat,
        make_user_jwt,
    ) -> None:
        outsider = make_user_jwt(id="99")
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                JoinChatCommand(chat_id=direct_chat.id, user_jwt_data=outsider)
            )

    async def test_already_member_raises_conflict(
        self,
        handler: JoinChatCommandHandler,
        user_jwt: UserJWTData,
        public_group_chat: Chat,
    ) -> None:
        with pytest.raises(AlreadyMemberError):
            await handler.handle(
                JoinChatCommand(chat_id=public_group_chat.id, user_jwt_data=user_jwt)
            )

    async def test_banned_user_can_rejoin_public_chat(
        self,
        handler: JoinChatCommandHandler,
        db_session: AsyncSession,
        chat_repository: ChatRepository,
        public_group_chat: Chat,
        make_user_jwt,
    ) -> None:
        target = make_user_jwt(id="2")
        member = await chat_repository.get_member_chat(public_group_chat.id, 2)
        assert member is not None
        member.ban(int(make_user_jwt(id="1").id))
        await db_session.commit()

        with pytest.raises(AlreadyMemberError):
            await handler.handle(JoinChatCommand(chat_id=public_group_chat.id, user_jwt_data=target))

        refreshed = await chat_repository.get_member_chat(public_group_chat.id, 2)
        assert refreshed is not None
        assert refreshed.is_banned is True

    async def test_join_nonexistent_chat_raises_not_found(
        self,
        handler: JoinChatCommandHandler,
        make_user_jwt,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                JoinChatCommand(chat_id=uuid4(), user_jwt_data=make_user_jwt(id="99"))
            )
