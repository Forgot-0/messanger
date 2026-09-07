from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.reactions import ReactionGroupDTO, ReactionUpdateWSDTO
from app.chats.models.chat import ChatFanoutStrategy
from app.chats.schemas.ws import WSEventType
from app.core.consumers.event import DictEventDTO

REACTION_EVENT_NAME = "chats.message.reaction_updated"
CHAT_DELETED_EVENT_NAME = "chats.chat.deleted"

CHAT_EVENT_TO_WS_TYPE: dict[str, str] = {
    "chats.message.sent": WSEventType.NEW_MESSAGE.value,
    "chats.message.modified": WSEventType.MESSAGE_EDITED.value,
    "chats.message.deleted": WSEventType.MESSAGE_DELETED.value,
    "chats.message.readed": WSEventType.MESSAGES_READ.value,
    "chats.member.added": WSEventType.MEMBER_JOINED.value,
    "chats.member.left": WSEventType.MEMBER_LEFT.value,
    "chats.member.kicked": WSEventType.MEMBER_KICK.value,
    "chats.member.banned": WSEventType.MEMBER_BANNED.value,
    "chats.chat.created": WSEventType.CHAT_CREATED.value,
    "chats.chat.updated": WSEventType.CHAT_UPDATED.value,
    CHAT_DELETED_EVENT_NAME: WSEventType.CHAT_DELETED.value,
    REACTION_EVENT_NAME: WSEventType.REACTION_UPDATED.value,
}

MESSAGE_HYDRATED_EVENTS: frozenset[str] = frozenset({
    "chats.message.sent",
    "chats.message.modified",
})

_DELTA_SKIP_FIELDS: frozenset[str] = frozenset({
    "chat_id",
    "groups",
    "recent_by_emoji",
})


def build_event_delta(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _DELTA_SKIP_FIELDS}


@dataclass(slots=True)
class WsEvent:
    type: str
    event_name: str
    event_id: str
    chat_id: UUID
    delta: dict[str, Any]
    ts: str
    fanout_strategy: ChatFanoutStrategy

    @classmethod
    def build(
        cls,
        event: DictEventDTO,
        ws_type: str,
        fanout_strategy: ChatFanoutStrategy,
    ) -> WsEvent:
        return cls(
            type=ws_type,
            event_name=event.event_name,
            event_id=str(event.event_id),
            chat_id=UUID(event.payload["chat_id"]),
            delta=build_event_delta(event.payload),
            ts=event.created_at.isoformat(),
            fanout_strategy=fanout_strategy,
        )


class MessagePayloadWS(BaseModel):
    event_id: str
    event_name: str
    event: dict[str, Any] = Field(default_factory=dict)
    message: MessageDTO | None = None
    reaction: ReactionUpdateWSDTO | None = None


def build_reaction_ws_dto(event: DictEventDTO) -> ReactionUpdateWSDTO:
    data = event.payload

    recent = data.get("recent_by_emoji") or {}
    groups: list[ReactionGroupDTO] = []
    for group in data.get("groups") or []:
        emoji = group["emoji"]
        groups.append(
            ReactionGroupDTO(
                emoji=emoji,
                count=group["count"],
                reacted_by_me=False,
                recent_user_ids=recent.get(emoji, []),
            )
        )

    return ReactionUpdateWSDTO(
        message_id=data["message_id"],
        chat_id=data["chat_id"],
        actor_id=data.get("actor_id", 0),
        action=data.get("action", "update"),
        groups=groups,
    )


def chunks(items: Iterable[int], size: int) -> Iterator[list[int]]:
    if size <= 0:
        raise ValueError("size must be greater than zero")

    batch: list[int] = []

    for item in items:
        batch.append(item)

        if len(batch) >= size:
            yield batch
            batch = []

    if batch:
        yield batch
