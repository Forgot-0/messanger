from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, update

from app.core.db.repository import CacheRepository, IRepository
from app.notifications.models.device import UserDeviceToken


@dataclass
class DeviceRepository(IRepository[UserDeviceToken], CacheRepository):
    _LIST_VERSION_KEY = "device:list"

    async def create(self, device: UserDeviceToken) -> None:
        self.session.add(device)

    async def get_active_by_user_id(self, user_id: int) -> list[UserDeviceToken]:
        result = await self.session.execute(
            select(UserDeviceToken).where(
                UserDeviceToken.user_id == user_id,
                UserDeviceToken.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def deactivate_tokens(self, tokens: Sequence[str]) -> None:
        await self.session.execute(
            update(UserDeviceToken)
            .where(UserDeviceToken.token.in_(tokens))
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )

