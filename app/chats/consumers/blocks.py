from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel

from app.chats.commands.blocks.apply import ApplyUserBlockCommand
from app.chats.config import chat_config
from app.core.consumers.event import DictEventDTO
from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.mediators.base import BaseMediator

router = KafkaRouter()

BLOCK_EVENT_STATES: dict[str, bool] = {
    chat_config.USER_BLOCKED_EVENT: True,
    chat_config.USER_UNBLOCKED_EVENT: False,
}


class UserBlockPayload(BaseModel):
    owner_id: int
    target_id: int


@router.subscriber(
    chat_config.PROFILE_TOPIC,
    group_id=chat_config.BLOCK_PROJECTION_GROUP_ID,
)
@inject
async def project_user_block(
    event: DictEventDTO,
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    blocked = BLOCK_EVENT_STATES.get(event.event_name)
    if blocked is None:
        return

    if not await idempotency_guard.try_acquire(
        group=chat_config.BLOCK_PROJECTION_GROUP_ID, event_id=event.event_id
    ):
        return

    payload = UserBlockPayload.model_validate(event.payload)
    try:
        await mediator.handle_command(
            ApplyUserBlockCommand(
                owner_id=payload.owner_id,
                target_id=payload.target_id,
                blocked=blocked,
            )
        )
    except Exception:
        await idempotency_guard.release(
            group=chat_config.BLOCK_PROJECTION_GROUP_ID, event_id=event.event_id
        )
        raise
