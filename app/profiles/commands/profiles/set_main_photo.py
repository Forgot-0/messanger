import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.profiles.exceptions import NotFoundProfileError, NotFoundProfilePhotoError
from app.profiles.repositories.photos import ProfilePhotoRepository
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetMainProfilePhotoCommand(BaseCommand):
    photo_id: UUID
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class SetMainProfilePhotoCommandHandler(BaseCommandHandler[SetMainProfilePhotoCommand, None]):
    session: AsyncSession
    profile_repository: ProfileRepository
    photo_repository: ProfilePhotoRepository
    event_bus: BaseEventBus

    async def handle(self, command: SetMainProfilePhotoCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        profile = await self.profile_repository.get_by_id(user_id, with_for_update=True)
        if profile is None:
            raise NotFoundProfileError(profile_id=user_id)

        photo = await self.photo_repository.get_own(command.photo_id, user_id)
        if photo is None:
            raise NotFoundProfilePhotoError(photo_id=str(command.photo_id))

        if profile.photo_id == photo.id:
            return

        photo.make_main()
        profile.set_photo(photo)

        await self.event_bus.publish(profile.pull_events())
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        logger.info(
            "Profile photo set as main",
            extra={"user_id": user_id, "photo_id": str(photo.id)},
        )
