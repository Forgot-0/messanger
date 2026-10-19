from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, and_, func, or_, select, update
from sqlalchemy.orm import aliased

from app.chats.models.join_request import ChatJoinRequest, JoinRequestStatus
from app.chats.models.profile import ChatUserProfile
from app.core.db.repository import IRepository
from app.core.utils import now_utc

JoinRequestRow = tuple[ChatJoinRequest, ChatUserProfile | None]


@dataclass
class ChatJoinRequestRepository(IRepository[ChatJoinRequest]):
    async def create(self, request: ChatJoinRequest) -> None:
        self.session.add(request)

    async def delete(self, request: ChatJoinRequest) -> None:
        await self.session.delete(request)

    async def get(
        self,
        chat_id: UUID,
        user_id: int,
        with_for_update: bool = False,
    ) -> ChatJoinRequest | None:
        stmt = select(ChatJoinRequest).where(
            ChatJoinRequest.chat_id == chat_id,
            ChatJoinRequest.user_id == user_id,
        )
        if with_for_update:
            stmt = stmt.with_for_update()

        result = await self.session.execute(stmt)
        return result.scalar()

    async def list_pending_for(
        self,
        chat_id: UUID,
        user_ids: Sequence[int],
        with_for_update: bool = False,
    ) -> list[ChatJoinRequest]:
        """Ожидающие заявки пакета. Порядок по `user_id` — не для выдачи, а чтобы два
        админа с пересекающимися пакетами брали строки в одном порядке и не ловили дедлок.
        """
        if not user_ids:
            return []

        stmt = (
            select(ChatJoinRequest)
            .where(
                ChatJoinRequest.chat_id == chat_id,
                ChatJoinRequest.user_id.in_(list(user_ids)),
                ChatJoinRequest.resolved_at.is_(None),
            )
            .order_by(ChatJoinRequest.user_id.asc())
        )
        if with_for_update:
            stmt = stmt.with_for_update()

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def decline_all(self, chat_id: UUID, resolved_by: int) -> int:
        """Отклонить всё одним UPDATE: 5000 заявок не должны стать 5000 команд и событий.

        `synchronize_session="fetch"` оставлен сознательно: на Postgres он не добавляет
        запроса (UPDATE уезжает с `RETURNING chat_id, user_id`), зато гасит в сессии уже
        загруженные заявки — без него они остались бы `PENDING` для текущей транзакции.
        """
        stmt = (
            update(ChatJoinRequest)
            .where(
                ChatJoinRequest.chat_id == chat_id,
                ChatJoinRequest.resolved_at.is_(None),
            )
            .values(
                status=JoinRequestStatus.DECLINED,
                resolved_at=now_utc(),
                resolved_by=resolved_by,
            )
            .execution_options(synchronize_session="fetch")
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        return int(result.rowcount)

    async def count_pending(self, chat_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ChatJoinRequest)
            .where(
                ChatJoinRequest.chat_id == chat_id,
                ChatJoinRequest.resolved_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_pending(
        self,
        chat_id: UUID,
        limit: int,
        last_requested_at: datetime | None = None,
        last_user_id: int | None = None,
    ) -> list[JoinRequestRow]:
        profile = aliased(ChatUserProfile)
        stmt = (
            select(ChatJoinRequest, profile)
            .outerjoin(profile, profile.user_id == ChatJoinRequest.user_id)
            .where(
                ChatJoinRequest.chat_id == chat_id,
                ChatJoinRequest.resolved_at.is_(None),
            )
            .order_by(ChatJoinRequest.requested_at.desc(), ChatJoinRequest.user_id.desc())
            .limit(limit + 1)
        )

        if last_requested_at is not None and last_user_id is not None:
            stmt = stmt.where(
                or_(
                    ChatJoinRequest.requested_at < last_requested_at,
                    and_(
                        ChatJoinRequest.requested_at == last_requested_at,
                        ChatJoinRequest.user_id < last_user_id,
                    ),
                )
            )

        result = await self.session.execute(stmt)
        return list(result.tuples())
