from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    Integer,
    column,
    func,
    or_,
    select,
    update,
    values,
)

from app.chats.models.invite import ChatInviteLink
from app.core.db.repository import IRepository
from app.core.utils import now_utc


@dataclass
class ChatInviteLinkRepository(IRepository[ChatInviteLink]):

    async def create(self, invite: ChatInviteLink) -> None:
        self.session.add(invite)

    async def get_by_id(self, invite_id: UUID) -> ChatInviteLink | None:
        stmt = select(ChatInviteLink).where(ChatInviteLink.id == invite_id)
        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_by_code(self, code: str) -> ChatInviteLink | None:
        stmt = select(ChatInviteLink).where(ChatInviteLink.code == code)
        result = await self.session.execute(stmt)
        return result.scalar()

    async def count_not_revoked(self, chat_id: UUID) -> int:
        stmt = select(func.count()).select_from(ChatInviteLink).where(
            ChatInviteLink.chat_id == chat_id,
            ChatInviteLink.revoked_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_page(
        self,
        chat_id: UUID,
        limit: int,
        last_invite_id: UUID | None = None,
    ) -> list[ChatInviteLink]:
        stmt = (
            select(ChatInviteLink)
            .where(ChatInviteLink.chat_id == chat_id)
            .order_by(ChatInviteLink.id.desc())
            .limit(limit + 1)
        )
        if last_invite_id is not None:
            stmt = stmt.where(ChatInviteLink.id < last_invite_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def credit_usage(self, counts: Mapping[UUID, int]) -> None:
        if not counts:
            return

        credited = values(
            column("invite_id", SAUUID(as_uuid=True)),
            column("delta", Integer),
            name="credited",
        ).data([(invite_id, int(delta)) for invite_id, delta in counts.items()])

        stmt = (
            update(ChatInviteLink)
            .where(ChatInviteLink.id == credited.c.invite_id)
            .values(usage_count=ChatInviteLink.usage_count + credited.c.delta)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def consume(self, invite_id: UUID) -> int | None:
        now = now_utc()
        stmt = (
            update(ChatInviteLink)
            .where(
                ChatInviteLink.id == invite_id,
                ChatInviteLink.revoked_at.is_(None),
                or_(ChatInviteLink.expires_at.is_(None), ChatInviteLink.expires_at > now),
                or_(
                    ChatInviteLink.usage_limit.is_(None),
                    ChatInviteLink.usage_count < ChatInviteLink.usage_limit,
                ),
            )
            .values(usage_count=ChatInviteLink.usage_count + 1)
            .returning(ChatInviteLink.usage_count)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
