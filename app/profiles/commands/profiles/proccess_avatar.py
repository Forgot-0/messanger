import logging
from dataclasses import dataclass
from uuid import uuid7

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.profiles.config import profile_config
from app.profiles.exceptions import (
    AvatarFileKeyError,
    AvatarNotImageTypeError,
    AvatarSizeError,
    NotFoundProfileError,
    ProfilePhotosLimitError,
)
from app.profiles.models.photo import ProfilePhoto
from app.profiles.repositories.photos import ProfilePhotoRepository
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.photo_storage import ProfilePhotoStorage

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class ProccessAvatarCommand(BaseCommand):
    user_id: int
    file_key: str


@dataclass(frozen=True)
class ProccessAvatarCommandHandler(BaseCommandHandler[ProccessAvatarCommand, None]):
    session: AsyncSession
    profile_repository: ProfileRepository
    photo_repository: ProfilePhotoRepository
    photo_storage: ProfilePhotoStorage
    event_bus: BaseEventBus

    async def handle(self, command: ProccessAvatarCommand) -> None:
        if not command.file_key.startswith(f"{command.user_id}/"):
            raise AvatarFileKeyError(file_key=command.file_key)

        profile = await self.profile_repository.get_by_id(command.user_id)
        if profile is None:
            raise NotFoundProfileError(profile_id=command.user_id)

        if await self.history_is_full(command.user_id):
            await self.photo_storage.drop_pending(command.file_key)
            raise ProfilePhotosLimitError(limit=profile_config.MAX_PROFILE_PHOTOS)

        try:
            data = await self.photo_storage.load_validated(command.file_key)
            rendered = await self.photo_storage.render(data)
        except (AvatarSizeError, AvatarNotImageTypeError):
            await self.photo_storage.drop_pending(command.file_key)
            raise

        photo_id = uuid7()
        avatars = await self.photo_storage.upload_variants(command.user_id, photo_id, rendered)

        profile = await self.profile_repository.get_by_id(command.user_id, with_for_update=True)
        if profile is None or await self.history_is_full(command.user_id):
            await self.photo_storage.delete_variants(command.user_id, avatars)
            await self.photo_storage.drop_pending(command.file_key)
            if profile is None:
                raise NotFoundProfileError(profile_id=command.user_id)
            raise ProfilePhotosLimitError(limit=profile_config.MAX_PROFILE_PHOTOS)

        photo = ProfilePhoto.create(photo_id=photo_id, user_id=command.user_id, avatars=avatars)
        await self.photo_repository.create(photo)
        profile.set_photo(photo)

        await self.event_bus.publish(profile.pull_events())
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        await self.photo_storage.drop_pending(command.file_key)

        logger.info(
            "Profile photo added", extra={
                "user_id": command.user_id, "photo_id": str(photo_id)
            }
        )

    async def history_is_full(self, user_id: int) -> bool:
        return await self.photo_repository.count(user_id) >= profile_config.MAX_PROFILE_PHOTOS
