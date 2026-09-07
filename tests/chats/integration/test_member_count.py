import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMemberCountShift:
    """Счётчик и лимит участников живут в одном UPDATE — иначе их пробивают гонкой."""

    async def test_shift_is_atomic_under_concurrency(
        self,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        group_chat: Chat,
    ) -> None:
        before = group_chat.member_count

        for _ in range(5):
            await chat_repository.shift_member_count(group_chat.id, delta=1)
        await db_session.commit()

        refreshed = await chat_repository.get_by_id(group_chat.id)
        assert refreshed is not None
        assert refreshed.member_count == before + 5

    async def test_shift_refuses_to_cross_the_limit(
        self,
        chat_repository: ChatRepository,
        group_chat: Chat,
    ) -> None:
        limit = group_chat.member_count

        assert await chat_repository.shift_member_count(group_chat.id, delta=1, limit=limit) is None

        refreshed = await chat_repository.get_by_id(group_chat.id)
        assert refreshed is not None
        assert refreshed.member_count == limit

    async def test_shift_returns_new_value_within_limit(
        self,
        chat_repository: ChatRepository,
        group_chat: Chat,
    ) -> None:
        before = group_chat.member_count

        new_count = await chat_repository.shift_member_count(
            group_chat.id, delta=1, limit=before + 1
        )

        assert new_count == before + 1
        # synchronize_session="fetch" держит объект в памяти согласованным с БД.
        assert group_chat.member_count == before + 1
