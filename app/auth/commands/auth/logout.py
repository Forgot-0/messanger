import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.config import auth_config
from app.auth.dtos.user import AuthUserJWTData
from app.auth.exceptions import NotFoundOrInactiveSessionError
from app.auth.repositories.session import SessionRepository, TokenBlacklistRepository
from app.auth.services.jwt import AuthJWTManager
from app.auth.services.session import SessionManager
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import JwtTokenType
from app.core.services.auth.exceptions import InvalidTokenError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class LogoutCommand(BaseCommand):
    refresh_token: str | None


@dataclass(frozen=True)
class LogoutCommandHandler(BaseCommandHandler[LogoutCommand, None]):
    session: AsyncSession
    session_manager: SessionManager
    jwt_manager: AuthJWTManager
    session_repository: SessionRepository
    token_blacklist: TokenBlacklistRepository
    event_bus: BaseEventBus

    async def handle(self, command: LogoutCommand) -> None:
        if command.refresh_token is None:
            raise InvalidTokenError(token=None)

        refresh_token = await self.jwt_manager.validate_token(command.refresh_token, token_type=JwtTokenType.REFRESH)
        await self.jwt_manager.revoke_token(refresh_token)

        session = await self.session_repository.get_active_by_device(
            user_id=int(refresh_token.sub),
            device_id=refresh_token.did
        )

        if not session:
            raise NotFoundOrInactiveSessionError

        session.deactivate()
        await self.token_blacklist.add_jwt_token(
            refresh_token.jti, timedelta(days=auth_config.REFRESH_TOKEN_EXPIRE_DAYS + 1)
        )

        await self.event_bus.publish(session.pull_events())
        await self.session.commit()
        logger.info("Logout user", extra={"sub": refresh_token.sub, "device_id": refresh_token.did})
