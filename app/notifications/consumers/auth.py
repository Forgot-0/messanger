from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel

from app.core.consumers.event import TypedEventDTO
from app.core.mediators.base import BaseMediator
from app.notifications.commands.devices.delete import DeleteUserDeviceCommand
from app.notifications.config import notification_config

router = KafkaRouter()
subscriber = router.subscriber(
    notification_config.AUTH_TOPIC,
    group_id=notification_config.AUTH_GROUP_ID,
)

class AuthLogoutEventDTO(BaseModel):
    user_id: int
    device_id: str


@subscriber(
    lambda msg: msg.headers.get("event_name") in notification_config.AUTH_LOGOUT_EVENT_NAMES
)
@inject
async def delete_device(
    event: TypedEventDTO[AuthLogoutEventDTO],
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        DeleteUserDeviceCommand(
            user_id=event.payload.user_id,
            device_id=event.payload.device_id
        )
    )

