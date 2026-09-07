from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import aliased, contains_eager, selectinload

from app.chats.exceptions import NotFoundChatError
from app.chats.models.chat import Chat, ChatType
from app.chats.models.chat_members import ChatMember
from app.chats.models.message import Message
from app.chats.models.profile import ChatUserProfile
from app.chats.models.read_receipts import ReadReceipt
from app.core.db.repository import CacheRepository, IRepository


@dataclass
class ChatRepository(IRepository[Chat], CacheRepository):
    _LIST_VERSION_KEY = "chats:list"

    async def get_by_id(
        self,
        chat_id: UUID,
        with_members: bool = False,
        with_for_update: bool = False,
        include_deleted: bool = False,
    ) -> Chat | None:
        stmt = select(Chat).where(Chat.id == chat_id)
        if not include_deleted:
            stmt = stmt.where(Chat.deleted_at.is_(None))

        if with_for_update:
            stmt = stmt.with_for_update()

        if with_members:
            stmt = stmt.options(
                selectinload(Chat.members).selectinload(ChatMember.role),
                selectinload(Chat.members).selectinload(ChatMember.profile),
            )

        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_direct_chat(self, user_id: int, other_user_id: int) -> Chat | None:
        member_a = aliased(ChatMember)
        member_b = aliased(ChatMember)

        stmt = (
            select(Chat)
            .join(member_a, and_(member_a.chat_id == Chat.id, member_a.user_id == user_id))
            .join(member_b, and_(member_b.chat_id == Chat.id, member_b.user_id == other_user_id))
            .where(
                Chat.type == ChatType.DIRECT,
                Chat.is_public.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar()

    async def allocate_message_seq(self, chat_id: UUID, message_date: datetime) -> int | None:
        stmt = (
            update(Chat)
            .where(Chat.id == chat_id, Chat.deleted_at.is_(None))
            .values(
                seq_counter=Chat.seq_counter + 1,
                last_activity_at=message_date,
            )
            .returning(Chat.seq_counter)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def shift_member_count(
        self,
        chat_id: UUID,
        delta: int,
        limit: int | None = None,
    ) -> int | None:
        stmt = (
            update(Chat)
            .where(Chat.id == chat_id, Chat.deleted_at.is_(None))
            .values(member_count=Chat.member_count + delta)
            .returning(Chat.member_count)
            .execution_options(synchronize_session="fetch")
        )
        if limit is not None:
            stmt = stmt.where(Chat.member_count + delta <= limit)

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, chat: Chat) -> None:
        self.session.add(chat)

    async def get_chat_and_member(
        self,
        chat_id: UUID,
        member_id: int
    ) -> tuple[Chat, ChatMember]:
        stmt = select(Chat, ChatMember).join(
            ChatMember,
            and_(ChatMember.chat_id == Chat.id, ChatMember.user_id == member_id),
        ).options(
            selectinload(ChatMember.role)
        ).where(
            Chat.id == chat_id,
            Chat.deleted_at.is_(None),
        )

        result = await self.session.execute(stmt)

        row = result.tuples().first()
        if row is None:
            raise NotFoundChatError(chat_id=str(chat_id))

        return row

    async def get_member_chat(
        self,
        chat_id: UUID,
        member_id: int,
        with_role: bool = True,
        with_profile: bool = False,
    ) -> ChatMember | None:
        stmt = select(ChatMember).where(
            ChatMember.chat_id == chat_id,
            ChatMember.user_id == member_id,
        )
        if with_role:
            stmt = stmt.options(selectinload(ChatMember.role))

        if with_profile:
            stmt = stmt.options(selectinload(ChatMember.profile))

        result = await self.session.execute(stmt)
        return result.scalar()

    async def delete_member(self, member: ChatMember) -> None:
        await self.session.delete(member)

    async def get_chat_members(
        self,
        chat_id: UUID,
        limit: int,
        cursor_user_id: int | None = None,
    ) -> list[ChatMember]:
        conditions = [
            ChatMember.chat_id == chat_id,
            ChatMember.active_criteria(),
        ]
        if cursor_user_id is not None:
            conditions.append(ChatMember.user_id > cursor_user_id)

        stmt = (
            select(ChatMember)
            .where(*conditions)
            .options(
                selectinload(ChatMember.role),
                selectinload(ChatMember.profile),
            )
            .order_by(ChatMember.user_id.asc())
            .limit(limit + 1)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def iter_member_ids(
        self,
        chat_id: UUID,
        batch_size: int = 2_000,
        role_ids: set[int] | None = None,
    ) -> AsyncIterator[list[int]]:
        last_user_id = -1
        while True:
            conditions = [
                ChatMember.chat_id == chat_id,
                ChatMember.active_criteria(),
                ChatMember.user_id > last_user_id,
            ]
            if role_ids is not None:
                conditions.append(ChatMember.role_id.in_(role_ids))

            stmt = (
                select(ChatMember.user_id)
                .where(*conditions)
                .order_by(ChatMember.user_id.asc())
                .limit(batch_size)
            )
            result = await self.session.execute(stmt)
            user_ids = list(result.scalars().all())
            if not user_ids:
                break
            yield [int(uid) for uid in user_ids]
            last_user_id = int(user_ids[-1])

    async def get_chats(
        self,
        user_id: int,
        limit: int,
        last_activity_at: datetime | None = None,
        chat_id: UUID | None = None,
    ) -> list[tuple[Chat, ChatMember, ReadReceipt | None, Message | None]]:
        author_profile = aliased(ChatUserProfile, name="author_profile")
        member_profile = aliased(ChatUserProfile, name="member_profile")

        stmt = (
            select(Chat, ChatMember, ReadReceipt, Message)
            .join(
                ChatMember,
                and_(ChatMember.chat_id == Chat.id, ChatMember.user_id == user_id),
            )
            .outerjoin(
                ReadReceipt,
                and_(ReadReceipt.chat_id == Chat.id, ReadReceipt.user_id == user_id),
            ).outerjoin(
                Message,
                and_(
                    Message.chat_id == Chat.id,
                    Message.seq == Chat.seq_counter,
                    Message.is_deleted.is_(False),
                ),
            ).outerjoin(
                author_profile, author_profile.user_id == Message.author_id
            ).outerjoin(
                member_profile, member_profile.user_id == ChatMember.user_id
            ).options(
                contains_eager(Message.profile.of_type(author_profile)),
                contains_eager(ChatMember.profile.of_type(member_profile)),
            ).where(
                ChatMember.user_id == user_id,
                ChatMember.active_criteria(),
                Chat.deleted_at.is_(None),
            ).order_by(
                Chat.last_activity_at.desc().nullslast(), Chat.id.desc()
            ).limit(limit + 1)
        )

        if last_activity_at is not None and chat_id is not None:
            stmt = stmt.where(
                or_(
                    Chat.last_activity_at < last_activity_at,
                    and_(
                        Chat.last_activity_at == last_activity_at,
                        Chat.id < chat_id,
                    ),
                )
            )

        result = await self.session.execute(stmt)
        return list(result.tuples())
