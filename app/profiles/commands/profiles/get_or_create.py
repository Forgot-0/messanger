import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class GetOrCreateProfileCommand(BaseCommand):
    user_id: int
    username: str


@dataclass(frozen=True)
class GetOrCreateProfileCommandHanler(BaseCommandHandler[GetOrCreateProfileCommand, ProfileDTO]):
    session: AsyncSession
    profile_repository: ProfileRepository
    event_bus: BaseEventBus

    async def handle(self, command: GetOrCreateProfileCommand) -> ProfileDTO:
        profile = await self.profile_repository.get_by_id(command.user_id)

        if profile is None:
            profile = Profile.create(
                username=command.username,
                user_id=command.user_id,
                display_name=None,
                specialization=None,
                bio=None
            )
            await self.profile_repository.create(profile)
            await self.event_bus.publish(profile.pull_events())
            await self.session.commit()
            await self.profile_repository.invalidate_cache()
            logger.info(
                "Profile create", extra={
                    "user_id": command.user_id
                }
            )

        return ProfileDTO.model_validate(profile)
