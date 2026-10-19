import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dtos.user import AuthUserJWTData, UserShortDTO
from app.auth.exceptions import NotFoundUserError, UsernameTakenError
from app.auth.models.user import User
from app.auth.repositories.user import UserRepository
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeUsernameCommand(BaseCommand):
    username: str

    user_jwt_data: AuthUserJWTData


@dataclass(frozen=True)
class ChangeUsernameCommandHandler(BaseCommandHandler[ChangeUsernameCommand, UserShortDTO]):
    session: AsyncSession
    event_bus: BaseEventBus
    user_repository: UserRepository

    async def handle(self, command: ChangeUsernameCommand) -> UserShortDTO:
        user_id = int(command.user_jwt_data.id)
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundUserError(user_by=user_id, user_field="id")

        username = User.validate_username(command.username)
        if username == user.username:
            return UserShortDTO(id=user.id, username=user.username, email=user.email)

        if await self.user_repository.is_username_taken(username, exclude_user_id=user.id):
            raise UsernameTakenError(username=username)

        old_username = user.username
        user.change_username(username)
        await self.event_bus.publish(user.pull_events())

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if "username" in str(exc.orig):
                raise UsernameTakenError(username=username) from exc
            raise

        await self.user_repository.invalidate_cache()

        logger.info(
            "Username changed",
            extra={"user_id": user.id, "old_username": old_username, "username": username},
        )
        return UserShortDTO(id=user.id, username=user.username, email=user.email)
