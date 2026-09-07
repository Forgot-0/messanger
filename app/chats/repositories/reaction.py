from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select, text, true

from app.chats.config import chat_config
from app.chats.models.reaction import (
    MessageReaction,
    MessageReactionCounter,
    ReactionGroupSnapshot,
)
from app.core.db.repository import IRepository
from app.core.utils import now_utc

_ADD_REACTION_SQL = text(
    """
    INSERT INTO message_reactions (message_id, user_id, emoji, chat_id, created_at, updated_at)
    VALUES (:message_id, :user_id, :emoji, :chat_id, :now, :now)
    ON CONFLICT (message_id, user_id, emoji) DO NOTHING
    RETURNING message_id
    """
)

_BUMP_COUNTER_UP_SQL = text(
    """
    INSERT INTO message_reaction_counters
        (message_id, emoji, chat_id, count, first_reacted_at, last_reacted_at)
    VALUES (:message_id, :emoji, :chat_id, 1, :now, :now)
    ON CONFLICT (message_id, emoji) DO UPDATE
        SET count = message_reaction_counters.count + 1,
            last_reacted_at = :now
    RETURNING count
    """
)

_REMOVE_REACTION_SQL = text(
    """
    DELETE FROM message_reactions
    WHERE message_id = :message_id AND user_id = :user_id AND emoji = :emoji
    RETURNING message_id
    """
)

_BUMP_COUNTER_DOWN_SQL = text(
    """
    UPDATE message_reaction_counters
    SET count = count - 1,
        last_reacted_at = :now
    WHERE message_id = :message_id AND emoji = :emoji
    RETURNING count
    """
)

_DROP_EMPTY_COUNTER_SQL = text(
    """
    DELETE FROM message_reaction_counters
    WHERE message_id = :message_id AND emoji = :emoji AND count <= 0
    """
)

@dataclass(slots=True)
class MessageReactionState:
    groups: list[ReactionGroupSnapshot] = field(default_factory=list)
    my_emojis: set[str] = field(default_factory=set)
    recent_by_emoji: dict[str, list[int]] = field(default_factory=dict)


@dataclass
class MessageReactionRepository(IRepository[MessageReaction]):

    async def count_distinct_emojis(self, message_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(MessageReactionCounter)
            .where(MessageReactionCounter.message_id == message_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_user_emojis(self, message_id: UUID, user_id: int) -> list[str]:
        stmt = select(MessageReaction.emoji).where(
            MessageReaction.message_id == message_id,
            MessageReaction.user_id == user_id,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_reaction(
        self,
        chat_id: UUID,
        message_id: UUID,
        user_id: int,
        emoji: str,
    ) -> int | None:
        now = now_utc()
        inserted = await self.session.execute(
            _ADD_REACTION_SQL,
            {
                "message_id": message_id,
                "user_id": user_id,
                "emoji": emoji,
                "chat_id": chat_id,
                "now": now,
            },
        )
        if inserted.first() is None:
            return None

        row = (
            await self.session.execute(
                _BUMP_COUNTER_UP_SQL,
                {
                    "message_id": message_id,
                    "emoji": emoji,
                    "chat_id": chat_id,
                    "now": now,
                },
            )
        ).one()
        return int(row[0])

    async def remove_reaction(
        self,
        message_id: UUID,
        user_id: int,
        emoji: str,
    ) -> int | None:
        now = now_utc()
        deleted = await self.session.execute(
            _REMOVE_REACTION_SQL,
            {"message_id": message_id, "user_id": user_id, "emoji": emoji},
        )
        if deleted.first() is None:
            return None

        row = (
            await self.session.execute(
                _BUMP_COUNTER_DOWN_SQL,
                {"message_id": message_id, "emoji": emoji, "now": now},
            )
        ).first()

        await self.session.execute(
            _DROP_EMPTY_COUNTER_SQL, {"message_id": message_id, "emoji": emoji}
        )

        if row is None:
            return 0

        return int(row[0])

    async def set_reactions(
        self,
        chat_id: UUID,
        message_id: UUID,
        user_id: int,
        emojis: Sequence[str],
    ) -> bool:
        locked = await self.session.execute(
            select(MessageReaction.emoji)
            .where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user_id,
            )
            .with_for_update()
        )
        current = set(locked.scalars().all())
        target = set(emojis)

        to_add = target - current
        to_remove = current - target
        if not to_add and not to_remove:
            return False

        for emoji in to_remove:
            await self.remove_reaction(message_id, user_id, emoji)
        for emoji in to_add:
            await self.add_reaction(chat_id, message_id, user_id, emoji)
        return True

    async def get_current_groups(self, message_id: UUID) -> list[ReactionGroupSnapshot]:
        stmt = (
            select(
                MessageReactionCounter.emoji.label("emoji"),
                MessageReactionCounter.count.label("cnt"),
            )
            .where(
                MessageReactionCounter.message_id == message_id,
                MessageReactionCounter.count > 0,
            )
            .order_by(
                MessageReactionCounter.count.desc(),
                MessageReactionCounter.emoji.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            ReactionGroupSnapshot(emoji=r.emoji, count=int(r.cnt))
            for r in rows
        ]

    async def get_reaction_state_for_messages(
        self, message_ids: Sequence[UUID], user_id: int
    ) -> dict[UUID, MessageReactionState]:
        ids = list(dict.fromkeys(message_ids))
        if not ids:
            return {}

        state: dict[UUID, MessageReactionState] = {}

        counters = (
            await self.session.execute(
                select(
                    MessageReactionCounter.message_id.label("message_id"),
                    MessageReactionCounter.emoji.label("emoji"),
                    MessageReactionCounter.count.label("cnt"),
                )
                .where(
                    MessageReactionCounter.message_id.in_(ids),
                    MessageReactionCounter.count > 0,
                )
                .order_by(
                    MessageReactionCounter.message_id,
                    MessageReactionCounter.count.desc(),
                    MessageReactionCounter.emoji.asc(),
                )
            )
        ).all()
        for row in counters:
            state.setdefault(row.message_id, MessageReactionState()).groups.append(
                ReactionGroupSnapshot(
                    emoji=row.emoji, count=int(row.cnt)
                )
            )

        if not state:
            return {}

        mine = (
            await self.session.execute(
                select(MessageReaction.message_id, MessageReaction.emoji).where(
                    MessageReaction.message_id.in_(list(state)),
                    MessageReaction.user_id == user_id,
                )
            )
        ).all()
        for my_row in mine:
            if my_row.message_id in state:
                state[my_row.message_id].my_emojis.add(my_row.emoji)

        if chat_config.REACTIONS_INCLUDE_RECENT_USERS:
            recent_lateral = (
                select(MessageReaction.user_id)
                .where(
                    MessageReaction.message_id == MessageReactionCounter.message_id,
                    MessageReaction.emoji == MessageReactionCounter.emoji,
                )
                .order_by(
                    MessageReaction.created_at.desc(),
                    MessageReaction.user_id.desc(),
                )
                .limit(chat_config.REACTION_RECENT_USERS_LIMIT)
                .lateral("recent_reactor")
            )
            recent = await self.session.execute(
                select(
                    MessageReactionCounter.message_id,
                    MessageReactionCounter.emoji,
                    recent_lateral.c.user_id,
                )
                .select_from(MessageReactionCounter)
                .join(recent_lateral, true())
                .where(
                    MessageReactionCounter.message_id.in_(list(state)),
                    MessageReactionCounter.count > 0,
                )
            )
            for row in recent.all():
                msg_state = state.get(row.message_id)
                if msg_state is not None:
                    msg_state.recent_by_emoji.setdefault(row.emoji, []).append(
                        int(row.user_id)
                    )

        return state

    async def get_users_by_emoji(
        self,
        message_id: UUID,
        emoji: str,
        limit: int,
        cursor_user_id: int | None = None,
    ) -> list[int]:
        stmt = (
            select(MessageReaction.user_id)
            .where(
                MessageReaction.message_id == message_id,
                MessageReaction.emoji == emoji,
            )
            .order_by(MessageReaction.user_id.asc())
            .limit(limit + 1)
        )
        if cursor_user_id is not None:
            stmt = stmt.where(MessageReaction.user_id > cursor_user_id)

        return list((await self.session.execute(stmt)).scalars().all())

    async def recount(self, message_id: UUID) -> None:
        await self.session.execute(
            text("DELETE FROM message_reaction_counters WHERE message_id = :message_id"),
            {"message_id": message_id},
        )
        await self.session.execute(
            text(
                """
                INSERT INTO message_reaction_counters
                    (message_id, emoji, chat_id, count, first_reacted_at, last_reacted_at)
                SELECT message_id, emoji, MIN(chat_id::text)::uuid, COUNT(*),
                       MIN(created_at), MAX(created_at)
                FROM message_reactions
                WHERE message_id = :message_id
                GROUP BY message_id, emoji
                """
            ),
            {"message_id": message_id},
        )
