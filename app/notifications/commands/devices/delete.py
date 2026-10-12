import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.notifications.exceptions import NotFoundUserDeviceError
from app.notifications.repositories.devices import DeviceRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteUserDeviceCommand(BaseCommand):
    user_id: int
    device_id: str


@dataclass(frozen=True)
class DeleteUserDeviceCommandHandler(BaseCommandHandler[DeleteUserDeviceCommand, None]):
    device_repository: DeviceRepository
    session: AsyncSession

    async def handle(self, command: DeleteUserDeviceCommand) -> None:
        device = await self.device_repository.get_device_by_user_did(
            user_id=command.user_id,
            device_id=command.device_id,
        )
        if device is None:
            raise NotFoundUserDeviceError

        device.deactivate()
        await self.session.commit()
        logger.info(
            "Delete user device", extra={
                "user_id": command.user_id,
                "device_id": command.device_id,
            }
        )
