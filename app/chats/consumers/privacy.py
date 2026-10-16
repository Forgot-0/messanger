from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel, Field

from app.chats.commands.privacy.apply import ApplyProfilePrivacyCommand
from app.chats.config import chat_config
from app.core.consumers.event import DictEventDTO
from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.mediators.base import BaseMediator

router = KafkaRouter()


class PrivacyExceptionsPayload(BaseModel):
    allow: list[int] = Field(default_factory=list)
    deny: list[int] = Field(default_factory=list)


class PrivacyUpdatedPayload(BaseModel):
    user_id: int
    rules: dict[str, str] = Field(default_factory=dict)
    exceptions: dict[str, PrivacyExceptionsPayload] = Field(default_factory=dict)


@router.subscriber(
    chat_config.PROFILE_TOPIC,
    group_id=chat_config.PRIVACY_PROJECTION_GROUP_ID,
)
@inject
async def project_profile_privacy(
    event: DictEventDTO,
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if event.event_name != chat_config.PRIVACY_UPDATED_EVENT:
        return

    if not await idempotency_guard.try_acquire(
        group=chat_config.PRIVACY_PROJECTION_GROUP_ID, event_id=event.event_id
    ):
        return

    payload = PrivacyUpdatedPayload.model_validate(event.payload)
    try:
        await mediator.handle_command(
            ApplyProfilePrivacyCommand(
                user_id=payload.user_id,
                rules=payload.rules,
                exceptions={
                    rule: {"allow": item.allow, "deny": item.deny}
                    for rule, item in payload.exceptions.items()
                },
                event_updated_at=event.created_at,
            )
        )
    except Exception:
        await idempotency_guard.release(
            group=chat_config.PRIVACY_PROJECTION_GROUP_ID, event_id=event.event_id
        )
        raise
