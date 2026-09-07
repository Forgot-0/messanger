import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
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
        device = UserDeviceToken.create(
            user_id=int(command.user_jwt_data.id),
            token=command.token,
            platform=command.platform,
            device_name=command.device_name
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
