import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeProfileUsernameCommand(BaseCommand):
    user_id: int
    username: str


@dataclass(frozen=True)
class ChangeProfileUsernameCommandHandler(BaseCommandHandler[ChangeProfileUsernameCommand, None]):
    session: AsyncSession
    profile_repository: ProfileRepository
    event_bus: BaseEventBus

    async def handle(self, command: ChangeProfileUsernameCommand) -> None:
        profile = await self.profile_repository.get_by_id(command.user_id, with_for_update=True)

        if profile is None:
            profile = Profile.create(
                user_id=command.user_id,
                username=command.username,
                display_name=None,
                specialization=None,
                bio=None,
            )
            await self.profile_repository.create(profile)
        else:
            profile.change_username(command.username)

        events = profile.pull_events()
        if not events:
            return

        await self.event_bus.publish(events)
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        logger.info(
            "Profile username synced",
            extra={"user_id": command.user_id, "username": command.username},
        )
