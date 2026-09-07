from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData
from app.notifications.commands.devices.create import CreateUserDeviceCommand
from app.notifications.schemas.devices.requests import CreateUserDeviceRequest

router = APIRouter(route_class=DishkaRoute)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED
)
async def create_new_device(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
    device_request: CreateUserDeviceRequest
) -> None:
    await mediator.handle_command(
        CreateUserDeviceCommand(
            platform=device_request.platform,
            token=device_request.token,
            device_name=device_request.device_name,
            user_jwt_data=user_jwt_data
        )
    )

