import pytest
from dishka import AsyncContainer

from app.chats.commands.chats.kick import KickMemberCommand, KickMemberCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotChatMemberError
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestKickMemberCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> KickMemberCommandHandler:
        return await request_container.get(KickMemberCommandHandler)

    async def test_owner_kicks_member(
        self,
        handler: KickMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            KickMemberCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
            )
        )

        kicked = await chat_repository.get_member_chat(group_chat.id, 2)
        assert kicked is None

    async def test_member_cannot_kick_self(
        self,
        handler: KickMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                KickMemberCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    target_user_id=1,
                )
            )

    async def test_regular_member_cannot_kick(
        self,
        handler: KickMemberCommandHandler,
        make_user_jwt,
        group_chat: Chat,
    ) -> None:

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                KickMemberCommand(
                    user_jwt_data=make_user_jwt(id="2"),
                    chat_id=group_chat.id,
                    target_user_id=3,
                )
            )

    async def test_kick_nonexistent_target_raises(
        self,
        handler: KickMemberCommandHandler,
        user_jwt: UserJWTData,
        group_chat: Chat,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await handler.handle(
                KickMemberCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    target_user_id=999,
                )
            )
