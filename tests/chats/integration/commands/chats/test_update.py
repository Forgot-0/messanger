from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.chats.update import UpdateChatCommand, UpdateChatCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotFoundChatError, SlowModeOutOfRangeError
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestUpdateChatCommand:
    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> UpdateChatCommandHandler:
        return await request_container.get(UpdateChatCommandHandler)

    async def test_owner_can_rename_group(
        self,
        handler: UpdateChatCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:

        await handler.handle(
            UpdateChatCommand(
                chat_id=group_chat.id,
                name="New Name",
                description="Updated",
                is_public=True,
                user_jwt_data=user_jwt,
            )
        )

        group = await chat_repository.get_by_id(group_chat.id)
        assert group is not None
        assert group.name == "New Name"
        assert group.description == "Updated"
        assert group.is_public is True

    async def test_non_member_cannot_update_chat(
        self,
        handler: UpdateChatCommandHandler,
        group_chat: Chat,
        make_user_jwt
    ) -> None:
        outsider = make_user_jwt(id="99")
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                UpdateChatCommand(
                    chat_id=group_chat.id,
                    name="Hijacked",
                    description=None,
                    is_public=None,
                    user_jwt_data=outsider,
                )
            )

    async def test_update_slow_mode_out_of_range_raises(
        self,
        handler: UpdateChatCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:

        with pytest.raises(SlowModeOutOfRangeError):
            await handler.handle(
                UpdateChatCommand(
                    chat_id=group_chat.id,
                    name="G",
                    description=None,
                    is_public=None,
                    slow_mode_seconds=999_999,
                    user_jwt_data=user_jwt,
                )
            )

    async def test_update_nonexistent_chat_raises(
        self,
        handler: UpdateChatCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                UpdateChatCommand(
                    chat_id=uuid4(),
                    name="X",
                    description=None,
                    is_public=None,
                    user_jwt_data=user_jwt,
                )
            )
