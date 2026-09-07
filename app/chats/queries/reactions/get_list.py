from dataclasses import dataclass
from uuid import UUID

from app.chats.dtos.reactions import MessageReactionsDTO, ReactionGroupDTO
from app.chats.exceptions import NotChatMemberError, NotFoundMessageError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.reaction import MessageReactionRepository
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetMessageReactionsQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    message_id: UUID

    emoji: str | None = None
    limit: int = 50
    cursor_user_id: int | None = None


@dataclass(frozen=True)
class GetMessageReactionsQueryHandler(
    BaseQueryHandler[GetMessageReactionsQuery, MessageReactionsDTO]
):
    chat_repository: ChatRepository
    message_repository: MessageRepository
    reaction_repository: MessageReactionRepository

    async def handle(self, query: GetMessageReactionsQuery) -> MessageReactionsDTO:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(
            query.chat_id, user_id, with_role=False
        )
        if member is None or member.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        message = await self.message_repository.get_by_id(query.message_id)
        if message is None or message.chat_id != query.chat_id:
            raise NotFoundMessageError(message_id=str(query.message_id))

        state = await self.reaction_repository.get_reaction_state_for_messages(
            [query.message_id], user_id
        )
        msg_state = state.get(query.message_id)
        groups = (
            []
            if msg_state is None
            else [
                ReactionGroupDTO(
                    emoji=g.emoji,
                    count=g.count,
                    reacted_by_me=g.emoji in msg_state.my_emojis,
                    recent_user_ids=msg_state.recent_by_emoji.get(g.emoji, []),
                )
                for g in msg_state.groups
            ]
        )

        users: list[int] = []
        has_next = False
        next_user_id: int | None = None

        if query.emoji is not None:
            limit = min(max(query.limit, 1), 100)
            page = await self.reaction_repository.get_users_by_emoji(
                message_id=query.message_id,
                emoji=query.emoji,
                limit=limit,
                cursor_user_id=query.cursor_user_id,
            )
            users = page[:limit]
            has_next = len(page) > limit
            next_user_id = users[-1] if has_next and users else None

        return MessageReactionsDTO(
            message_id=query.message_id,
            groups=groups,
            emoji=query.emoji,
            users=users,
            has_next=has_next,
            next_user_id=next_user_id,
        )
