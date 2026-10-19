from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.chats.models.join_request import ChatJoinRequest
from app.chats.models.profile import ChatUserProfile
from app.core.db.repository import IRepository

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
