from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.reactions import ReactionGroupDTO
from app.chats.repositories.reaction import MessageReactionRepository


@dataclass
class ReactionAttachService:
    reaction_repository: MessageReactionRepository

    async def attach(
        self, messages: Iterable[MessageDTO], user_id: int
    ) -> list[MessageDTO]:
        message_list = list(messages)
        by_id: dict[UUID, list[MessageDTO]] = {}

        for message in message_list:
            for node in (message, message.reply_to, message.forwarded_from):
                if node is not None:
                    by_id.setdefault(node.id, []).append(node)

        if not by_id:
            return message_list

        state = await self.reaction_repository.get_reaction_state_for_messages(
            list(by_id), user_id
        )

        for message_id, nodes in by_id.items():
            msg_state = state.get(message_id)
            groups = (
                []
                if msg_state is None
                else [
                    ReactionGroupDTO(
                        emoji=group.emoji,
                        count=group.count,
                        reacted_by_me=group.emoji in msg_state.my_emojis,
                        recent_user_ids=msg_state.recent_by_emoji.get(group.emoji, []),
                    )
                    for group in msg_state.groups
                ]
            )
            for node in nodes:
                node.reactions = groups

        return message_list
