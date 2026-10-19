from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel

from app.core.commands import BaseCommand
from app.core.consumers.event import DictEventDTO
from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.mediators.base import BaseMediator
from app.profiles.commands.contacts.register_identifier import RegisterUserIdentifierCommand
from app.profiles.commands.profiles.change_username import ChangeProfileUsernameCommand
from app.profiles.commands.profiles.get_or_create import GetOrCreateProfileCommand
from app.profiles.config import profile_config

router = KafkaRouter()


class VerifiedUserPayload(BaseModel):
    user_id: int
    username: str
    email: str


class ChangedUsernamePayload(BaseModel):
    user_id: int
    username: str


def commands_for(event: DictEventDTO) -> list[BaseCommand]:
    if event.event_name == profile_config.USER_VERIFIED_EVENT:
        verified = VerifiedUserPayload.model_validate(event.payload)
        return [
            GetOrCreateProfileCommand(user_id=verified.user_id, username=verified.username),
            RegisterUserIdentifierCommand(user_id=verified.user_id, email=verified.email),
        ]

    if event.event_name == profile_config.USERNAME_CHANGED_EVENT:
        changed = ChangedUsernamePayload.model_validate(event.payload)
        return [ChangeProfileUsernameCommand(user_id=changed.user_id, username=changed.username)]

    return []


@router.subscriber(
    profile_config.USER_TOPIC,
    group_id=profile_config.USER_VERIFIED_GROUP_ID,
)
@inject
async def on_user_event(
    event: DictEventDTO,
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    commands = commands_for(event)
    if not commands:
        return

    if not await idempotency_guard.try_acquire(
        group=profile_config.USER_VERIFIED_GROUP_ID, event_id=event.event_id
    ):
        return

    try:
        for command in commands:
            await mediator.handle_command(command)
    except Exception:
        await idempotency_guard.release(
            group=profile_config.USER_VERIFIED_GROUP_ID, event_id=event.event_id
        )
        raise
