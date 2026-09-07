import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.exceptions import AccessDeniedError
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateProfileCommand(BaseCommand):
    profile_id: int

    display_name: str | None
    bio: str | None
    skills: set[str] | None
    date_birthday: date | None
    specialization: str | None

    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class UpdateProfileCommandHandler(BaseCommandHandler[UpdateProfileCommand, None]):
    session: AsyncSession
    profile_repository: ProfileRepository
    rbac_manager: RBACManagerInterface
    event_bus: BaseEventBus

    async def handle(self, command: UpdateProfileCommand) -> None:
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

        profile.update(
            name=command.display_name,
            bio=command.bio,
            specialization=command.specialization,
            date_birthday=command.date_birthday,
            skills=command.skills or set(),
        )
        await self.event_bus.publish(profile.pull_events())
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        logger.info(
            "Update profile",
            extra={
                "user_id": command.user_jwt_data.id,
                "profile_id": command.profile_id,
                "display_name":command.display_name,
                "bio": command.bio,
                "skills": list(command.skills) if command.skills else None
            }
        )
