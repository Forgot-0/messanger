import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.exceptions import AccessDeniedError
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class RemoveContactToProfileCommand(BaseCommand):
    profile_id: int
    provider: str

    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class RemoveContactToProfileCommandHandler(BaseCommandHandler[RemoveContactToProfileCommand, None]):
    session: AsyncSession
    profile_repository: ProfileRepository
    rbac_manager: RBACManagerInterface

    async def handle(self, command: RemoveContactToProfileCommand) -> None:
        profile = await self.profile_repository.get_by_id(command.profile_id)

        if profile is None:
            raise NotFoundProfileError(profile_id=command.profile_id)

        if (
            profile.id != int(command.user_jwt_data.id) and
            not self.rbac_manager.check_permission(command.user_jwt_data, {"profile:update", "user:update" })
        ):
            raise AccessDeniedError(
                need_permissions={"profile:update", "user:update" } - set(command.user_jwt_data.permissions)
            )

        profile.remove_contact(command.provider)
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        logger.info(
            "Remove contact profile", extra={
                "removed_by": command.user_jwt_data.id,
                "provider": command.provider,
                "profile_id": command.profile_id
            }
        )
