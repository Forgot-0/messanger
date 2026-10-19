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
from app.profiles.services.photo_storage import ProfilePhotoStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteProfilePhotoCommand(BaseCommand):
    user_jwt_data: UserJWTData
    photo_id: UUID | None = None


@dataclass(frozen=True)
class DeleteProfilePhotoCommandHandler(BaseCommandHandler[DeleteProfilePhotoCommand, None]):
    session: AsyncSession
    profile_repository: ProfileRepository
    photo_repository: ProfilePhotoRepository
    photo_storage: ProfilePhotoStorage
    event_bus: BaseEventBus

    async def handle(self, command: DeleteProfilePhotoCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        profile = await self.profile_repository.get_by_id(user_id, with_for_update=True)
        if profile is None:
            raise NotFoundProfileError(profile_id=user_id)

        photo_id = command.photo_id or profile.photo_id
        photo = await self.photo_repository.get_own(photo_id, user_id) if photo_id else None

        if photo is None:
            if command.photo_id is not None:
                raise NotFoundProfilePhotoError(photo_id=str(command.photo_id))
            return

        stale = dict(photo.avatars)
        await self.photo_repository.delete(photo)

        if profile.photo_id == photo.id:
            await self.session.flush()
            profile.set_photo(await self.photo_repository.get_latest(user_id))

        await self.event_bus.publish(profile.pull_events())
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        await self.photo_storage.delete_variants(user_id, stale)

        logger.info("Profile photo deleted", extra={"user_id": user_id, "photo_id": str(photo.id)})
