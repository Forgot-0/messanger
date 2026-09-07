import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class GetOrCreateProfileCommand(BaseCommand):
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class GetOrCreateProfileCommandHanler(BaseCommandHandler[GetOrCreateProfileCommand, ProfileDTO]):
    session: AsyncSession
    profile_repository: ProfileRepository

    async def handle(self, command: GetOrCreateProfileCommand) -> ProfileDTO:
        profile = await self.profile_repository.get_by_id(int(command.user_jwt_data.id))

        if profile is None:
            profile = Profile.create(
                username=command.user_jwt_data.username,
                user_id=int(command.user_jwt_data.id),
                display_name=None,
                specialization=None,
                bio=None
            )
            await self.profile_repository.create(profile)
            await self.session.commit()
            await self.profile_repository.invalidate_cache()
            logger.info(
                "Profile create", extra={
                    "user_id": command.user_jwt_data.id
                }
            )

        return ProfileDTO.model_validate(profile)
