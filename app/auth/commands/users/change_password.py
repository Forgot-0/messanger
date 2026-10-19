import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.config import auth_config
from app.auth.dtos.user import AuthUserJWTData
from app.auth.exceptions import NotFoundUserError, PasswordMismatchError
from app.auth.repositories.session import TokenBlacklistRepository
from app.auth.repositories.user import UserRepository
from app.auth.services.hash import HashService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ChangePasswordCommand(BaseCommand):
    old_password: str
    new_password: str
    new_password_repeat: str

    user_jwt_data: AuthUserJWTData



@dataclass(frozen=True)
class ChangePasswordCommandHandler(BaseCommandHandler[ChangePasswordCommand, None]):
    session: AsyncSession
    event_bus: BaseEventBus
    user_repository: UserRepository
    token_repository: TokenBlacklistRepository
    hash_service: HashService

    async def handle(self, command: ChangePasswordCommand) -> None:
        user = await self.user_repository.get_by_id(user_id=int(command.user_jwt_data.id))

        if not user:
            raise NotFoundUserError(user_by="1", user_field="id")

        if (
            user.password_hash is None or
            self.hash_service.verify_password(command.old_password, user.password_hash) or
            command.new_password != command.new_password_repeat
        ):
            raise PasswordMismatchError

        user.password_reset(self.hash_service.hash_password(command.new_password))
        await self.token_repository.add_user(user.id, expiration=timedelta(days=auth_config.REFRESH_TOKEN_EXPIRE_DAYS))

        await self.event_bus.publish(user.pull_events())
        await self.session.commit()

        logger.info("Password change", extra={"user_id": user.id, "username": user.username})
