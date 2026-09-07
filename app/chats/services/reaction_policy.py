from dataclasses import dataclass

from app.chats.config import chat_config
from app.chats.exceptions import (
    AccessDeniedChatError,
    InvalidReactionError,
    ReactionNotAllowedError,
    ReactionsDisabledError,
)
from app.chats.models.chat import Chat, ChatReactionsMode
from app.chats.models.chat_members import ChatMember


@dataclass(slots=True)
class ReactionPolicy:
    def ensure_can_react(self, chat: Chat, member: ChatMember) -> None:
        if member.is_muted:
            raise AccessDeniedChatError(
                chat_id=str(chat.id), requester_id=member.user_id
            )
        if chat.reactions_mode == ChatReactionsMode.NONE:
            raise ReactionsDisabledError(chat_id=str(chat.id))

    def validate_emoji(self, chat: Chat, emoji: str) -> None:
        if emoji not in chat_config.DEFAULT_REACTIONS:
            raise InvalidReactionError(emoji=emoji[:64])

        if chat.reactions_mode == ChatReactionsMode.NONE:
            raise ReactionsDisabledError(chat_id=str(chat.id))

        if (
            chat.reactions_mode == ChatReactionsMode.SOME
            and emoji not in set(chat.allowed_reactions or ())
        ):
            raise ReactionNotAllowedError(
                emoji=emoji, allowed=list(chat.allowed_reactions or [])
            )

    def validate(self, chat: Chat, member: ChatMember, emoji: str) -> None:
        self.ensure_can_react(chat, member)
        self.validate_emoji(chat, emoji)
