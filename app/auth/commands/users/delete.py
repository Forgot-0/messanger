import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.config import auth_config
from app.auth.dtos.user import AuthUserJWTData
from app.auth.exceptions import NotFoundUserError
from app.auth.repositories.session import SessionRepository, TokenBlacklistRepository
from app.auth.repositories.user import UserRepository
from app.auth.services.rbac import AuthRBACManager
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.exceptions import AccessDeniedError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class DeleteUserCommand(BaseCommand):
    user_id: int

    user_jwt_data: AuthUserJWTData


@dataclass(frozen=True)
class DeleteUserCommandHandler(BaseCommandHandler[DeleteUserCommand, None]):
    session: AsyncSession
    user_repository: UserRepository
    session_repository: SessionRepository
    token_repository: TokenBlacklistRepository
    rbac_manager: AuthRBACManager
    event_bus: BaseEventBus

    async def handle(self, command: DeleteUserCommand) -> None:
        user = await self.user_repository.get_by_id(command.user_id)
        if user is None:
            raise NotFoundUserError(user_by=command.user_id, user_field="user_id")

        if (
            user.id != int(command.user_jwt_data.id) and
            not self.rbac_manager.check_permission(command.user_jwt_data, {"user:update" })
        ):
            raise AccessDeniedError(need_permissions={"user:delete", "user:owner"})

        user.delete()
        await self.token_repository.add_user(user.id, expiration=timedelta(days=auth_config.REFRESH_TOKEN_EXPIRE_DAYS))
        await self.event_bus.publish(user.pull_events())
        await self.session.commit()

        logger.info(
            "User delete account", {
                "target_user_id": command.user_id,
                "delete_by": command.user_jwt_data.id
            }
        )
