from uuid import UUID

from app.chats.config import chat_config
from app.chats.models.reaction import ReactionUpdatedEvent
from app.chats.repositories.reaction import MessageReactionRepository


async def build_reaction_event(
    reaction_repository: MessageReactionRepository,
    *,
    chat_id: UUID,
    message_id: UUID,
    actor_id: int,
    action: str,
) -> ReactionUpdatedEvent:
    groups = await reaction_repository.get_current_groups(message_id)

    recent_by_emoji: dict[str, list[int]] = {}
    if chat_config.REACTIONS_INCLUDE_RECENT_USERS and groups:
        state = await reaction_repository.get_reaction_state_for_messages(
            [message_id], actor_id
        )
        msg_state = state.get(message_id)
        if msg_state is not None:
            recent_by_emoji = msg_state.recent_by_emoji

    return ReactionUpdatedEvent(
        message_id=str(message_id),
        chat_id=str(chat_id),
        actor_id=actor_id,
        action=action,
        groups=groups,
        recent_by_emoji=recent_by_emoji,
    )
