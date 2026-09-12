from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel

from app.core.consumers.event import TypedEventDTO
from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.mediators.base import BaseMediator
from app.profiles.commands.contacts.register_identifier import RegisterUserIdentifierCommand
from app.profiles.commands.profiles.get_or_create import GetOrCreateProfileCommand
from app.profiles.config import profile_config

router = KafkaRouter()
subscriber = router.subscriber(
    profile_config.USER_TOPIC,
    group_id=profile_config.USER_VERIFIED_GROUP_ID,
)

class VerifiedUserPayload(BaseModel):
    user_id: int
    username: str
    email: str


@subscriber(filter=lambda msg: msg.headers.get("event_name") == profile_config.USER_VERIFIED_EVENT)
@inject
async def on_user_verified(
    event: TypedEventDTO[VerifiedUserPayload],
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if not await idempotency_guard.try_acquire(
        group=profile_config.USER_VERIFIED_GROUP_ID, event_id=event.event_id
    ):
        return

    try:
        await mediator.handle_command(
            GetOrCreateProfileCommand(user_id=event.payload.user_id, username=event.payload.username)
        )
        await mediator.handle_command(
            RegisterUserIdentifierCommand(user_id=event.payload.user_id, email=event.payload.email)
        )
    except Exception:
        await idempotency_guard.release(
            group=profile_config.USER_VERIFIED_GROUP_ID, event_id=event.event_id
        )
        raise

@subscriber
async def pass_(
    event
) -> None:
    return
