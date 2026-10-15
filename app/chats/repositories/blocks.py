from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.chats.models.blocks import ChatUserBlock
from app.chats.models.chat_members import ChatMember
from app.core.db.repository import IRepository


@dataclass
class ChatUserBlockRepository(IRepository[ChatUserBlock]):

    async def block(self, owner_id: int, target_id: int) -> bool:
        stmt = (
            insert(ChatUserBlock)
            .values(owner_id=owner_id, target_id=target_id)
            .on_conflict_do_nothing(index_elements=[ChatUserBlock.owner_id, ChatUserBlock.target_id])
            .returning(ChatUserBlock.owner_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def unblock(self, owner_id: int, target_id: int) -> bool:
        stmt = (
            delete(ChatUserBlock)
            .where(ChatUserBlock.owner_id == owner_id, ChatUserBlock.target_id == target_id)
            .returning(ChatUserBlock.owner_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def blockers_of(self, target_id: int, owner_ids: Collection[int]) -> set[int]:
        if not owner_ids:
            return set()

        stmt = select(ChatUserBlock.owner_id).where(
            ChatUserBlock.target_id == target_id,
            ChatUserBlock.owner_id.in_(list(owner_ids)),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def is_blocked_between(self, user_id: int, other_user_id: int) -> bool:
        stmt = select(
            exists().where(
                or_(
                    and_(ChatUserBlock.owner_id == user_id, ChatUserBlock.target_id == other_user_id),
                    and_(ChatUserBlock.owner_id == other_user_id, ChatUserBlock.target_id == user_id),
                )
            )
        )
        result = await self.session.execute(stmt)
        return bool(result.scalar())

    async def blocked_direct_peer(self, chat_id: UUID, user_id: int) -> int | None:
        peer = aliased(ChatMember)
        stmt = (
            select(peer.user_id)
            .where(
                peer.chat_id == chat_id,
                peer.user_id != user_id,
                exists().where(
                    or_(
                        and_(
                            ChatUserBlock.owner_id == peer.user_id,
                            ChatUserBlock.target_id == user_id,
                        ),
                        and_(
                            ChatUserBlock.owner_id == user_id,
                            ChatUserBlock.target_id == peer.user_id,
                        ),
                    )
                ),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        peer_id = result.scalar()
        return int(peer_id) if peer_id is not None else None
