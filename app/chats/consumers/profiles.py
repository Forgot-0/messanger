import logging

from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel, Field

from app.chats.commands.profiles.upsert import UpsertProfileProjectionCommand
from app.chats.config import chat_config
from app.core.consumers.event import TypedEventDTO
from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.mediators.base import BaseMediator

logger = logging.getLogger(__name__)

router = KafkaRouter()

subscriber = router.subscriber(
    chat_config.PROFILE_TOPIC,
    group_id=chat_config.PROFILE_PROJECTION_GROUP_ID,
)

PROFILE_EVENT_NAMES = frozenset({
    "profiles.profile.created",
    "profiles.profile.updated",
})

class ProfileDataEvent(BaseModel):
    user_id: int
    username: str
    avatars: dict

    display_name: str | None = None
    bio: str | None = None
    specialization: str | None = None
    date_birthday: str | None = None
    skills: list[str] = Field(default_factory=list)


@subscriber(filter=lambda msg: msg.headers.get("event_name") in PROFILE_EVENT_NAMES)
@inject
async def route_profile_delivery_event(
    event: TypedEventDTO[ProfileDataEvent],
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if not await idempotency_guard.try_acquire(
        group=chat_config.PROFILE_PROJECTION_GROUP_ID, event_id=event.event_id
    ):
        return

    try:
        await mediator.handle_command(
            UpsertProfileProjectionCommand(
                user_id=event.payload.user_id,
                username=event.payload.username,
                display_name=event.payload.display_name,
                avatars=event.payload.avatars,
                event_id=event.event_id,
                event_updated_at=event.created_at
            )
        )
    except Exception:
        await idempotency_guard.release(
            group=chat_config.PROFILE_PROJECTION_GROUP_ID,
            event_id=event.event_id
        )
        raise
