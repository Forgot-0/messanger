import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.notifications.exceptions import AlreadyExistDeviceTokenError
from app.notifications.models.device import PlatformEnum, UserDeviceToken
from app.notifications.repositories.devices import DeviceRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateUserDeviceCommand(BaseCommand):
    platform: PlatformEnum
    token: str
    device_name: str

    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class CreateUserDeviceCommandHandler(BaseCommandHandler[CreateUserDeviceCommand, None]):
    device_repository: DeviceRepository
    session: AsyncSession

    async def handle(self, command: CreateUserDeviceCommand) -> None:
        device = await self.device_repository.get_device_by_user_token(
            user_id=int(command.user_jwt_data.id),
            token=command.token,
        )
        if device and device.is_active:
            raise AlreadyExistDeviceTokenError

        if device and device.is_active is False:
            device.activate()

        else:
            device = UserDeviceToken.create(
                user_id=int(command.user_jwt_data.id),
                token=command.token,
                platform=command.platform,
                device_name=command.device_name,
                did=command.user_jwt_data.device_id
            )

            await self.device_repository.create(device)

        await self.session.commit()
        logger.info(
            "Create new user device token", extra={
                "user_id": command.user_jwt_data.id,
                "platform": command.platform,
                "device_name": command.device_name
            }
        )
