from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel

from app.auth.commands.users.send_verify import SendVerifyCommand
from app.auth.config import auth_config
from app.auth.models.user import CreatedUserEvent
from app.core.consumers.event import TypedEventDTO
from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.mediators.base import BaseMediator

router = KafkaRouter()

subscriber = router.subscriber(
    auth_config.USER_TOPIC,
    group_id=auth_config.SEND_VERIFY_GROUP_ID,
)

class CreatedUserPayload(BaseModel):
    email: str
    username: str


@subscriber(filter=lambda msg: msg.headers.get("event_name") == CreatedUserEvent.get_name())
@inject
async def send_verify_on_user_created(
    event: TypedEventDTO[CreatedUserPayload],
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if not await idempotency_guard.try_acquire(
        group=auth_config.SEND_VERIFY_GROUP_ID, event_id=event.event_id
    ):
        return

    try:
        await mediator.handle_command(
            SendVerifyCommand(
                email=event.payload.email,
            )
        )
    except Exception:
        await idempotency_guard.release(
            group=auth_config.SEND_VERIFY_GROUP_ID, event_id=event.event_id
        )
        raise


@subscriber
async def pass_(
    _event
) -> None:
    return
