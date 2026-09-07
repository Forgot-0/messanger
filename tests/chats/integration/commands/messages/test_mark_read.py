import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.messages.mark_read import MarkAsReadCommand, MarkAsReadCommandHandler
from app.chats.exceptions import NotFoundChatError
from app.chats.models.chat import Chat
from app.chats.models.read_receipts import ReadReceipt
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMarkAsReadCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> MarkAsReadCommandHandler:
        return await request_container.get(MarkAsReadCommandHandler)

    async def test_member_marks_message_as_read(
        self,
        handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        await handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=5, user_jwt_data=user_jwt)
        )

        result = await db_session.execute(
            select(ReadReceipt).where(
                ReadReceipt.chat_id == group_chat.id,
                ReadReceipt.user_id == int(user_jwt.id),
            )
        )
        receipt = result.scalar()
        assert receipt is not None
        assert receipt.last_read_message_seq == 5

    async def test_mark_read_is_idempotent_and_monotonic(
        self,
        handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        await handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=10, user_jwt_data=user_jwt)
        )
        await handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=5, user_jwt_data=user_jwt)
        )

        result = await db_session.execute(
            select(ReadReceipt).where(
                ReadReceipt.chat_id == group_chat.id,
                ReadReceipt.user_id == int(user_jwt.id),
            )
        )
        receipt = result.scalar()
        assert receipt is not None
        assert receipt.last_read_message_seq == 10

    async def test_non_member_cannot_mark_read(
        self,
        handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        outsider = make_user_jwt(id="999")
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                MarkAsReadCommand(chat_id=group_chat.id, message_seq=1, user_jwt_data=outsider)
            )
