
import pytest
from dishka import AsyncContainer

from app.chats.commands.chats.create import CreateChatCommand, CreateChatCommandHandler
from app.chats.models.chat import ChatFanoutStrategy, ChatType
from app.chats.models.permission import ChatRolesEnum
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestCreateChatCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> CreateChatCommandHandler:
        return await request_container.get(CreateChatCommandHandler)

    async def test_create_direct_chat_persists_two_members(
        self,
        handler: CreateChatCommandHandler,
        chat_repository: ChatRepository,
        user_jwt: UserJWTData,
    ) -> None:
        cmd = CreateChatCommand(
            name=None,
            description=None,
            chat_type=ChatType.DIRECT,
            member_ids=[2],
            is_public=False,
            user_jwt_data=user_jwt,
        )
        dto = await handler.handle(cmd)
        chat = await chat_repository.get_by_id(dto.id, with_members=True)
        assert chat is not None
        assert chat.member_count == 2
        assert chat.members[0].role_id == ChatRolesEnum.DIRECT_MEMBER.value.id
        assert chat.members[1].role_id == ChatRolesEnum.DIRECT_MEMBER.value.id
        assert chat.name is None
        assert chat.description is None
        assert chat.fanout_strategy == ChatFanoutStrategy.FANOUT_ON_WRITE

    async def test_create_group_chat_with_name_and_description(
        self,
        handler: CreateChatCommandHandler,
        chat_repository: ChatRepository,
        user_jwt: UserJWTData
    ) -> None:
        cmd = CreateChatCommand(
            name="My Group",
            description="Best group",
            chat_type=ChatType.GROUP,
            member_ids=[10, 20, 30],
            is_public=True,
            user_jwt_data=user_jwt,
        )
        dto = await handler.handle(cmd)

        chat = await chat_repository.get_by_id(dto.id, with_members=True)
        assert chat is not None
        assert chat.member_count == 4
        assert chat.name == "My Group"
        assert chat.description == "Best group"
        assert chat.is_public

    async def test_create_public_channel(
        self,
        handler: CreateChatCommandHandler,
        chat_repository: ChatRepository,
        user_jwt: UserJWTData
    ) -> None:
        cmd = CreateChatCommand(
            name="News Channel",
            description=None,
            chat_type=ChatType.CHANNEL,
            member_ids=[5, 6, 7],
            is_public=True,
            user_jwt_data=user_jwt,
        )
        dto = await handler.handle(cmd)

        chat = await chat_repository.get_by_id(dto.id, with_members=True)
        assert chat is not None
        assert chat.type == ChatType.CHANNEL
        assert chat.member_count == 4
        assert chat.name == "News Channel"
        assert chat.description is None
        assert chat.is_public

    async def test_create_group_with_slow_mode(
        self,
        handler: CreateChatCommandHandler,
        chat_repository: ChatRepository,
        user_jwt: UserJWTData
    ) -> None:
        cmd = CreateChatCommand(
            name="Slow Group",
            description=None,
            chat_type=ChatType.GROUP,
            member_ids=[1, 2],
            is_public=False,
            user_jwt_data=user_jwt,
            slow_mode_seconds=60,
        )
        dto = await handler.handle(cmd)

        chat = await chat_repository.get_by_id(dto.id, with_members=True)
        assert chat is not None
        assert chat.slow_mode_seconds == 60
