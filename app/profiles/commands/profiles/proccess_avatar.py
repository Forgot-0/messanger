import io
import logging
from dataclasses import dataclass

import magic
import pyvips
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.storage.dtos import UploadFile
from app.core.services.storage.service import StorageService
from app.profiles.config import profile_config
from app.profiles.exceptions import AvatarFileKeyError, AvatarNotImageTypeError, AvatarSizeError, NotFoundProfileError
from app.profiles.models.profile import SizeAvatar
from app.profiles.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class ProccessAvatarCommand(BaseCommand):
    user_id: int
    file_key: str


@dataclass(frozen=True)
class ProccessAvatarCommandHandler(BaseCommandHandler[ProccessAvatarCommand, None]):
    session: AsyncSession
    storage_service: StorageService
    profile_repository: ProfileRepository
    event_bus: BaseEventBus

    async def handle(self, command: ProccessAvatarCommand) -> None:
        if not command.file_key.startswith(f"{command.user_id}/"):
            raise AvatarFileKeyError(file_key=command.file_key)

        profile = await self.profile_repository.get_by_id(command.user_id)
        if profile is None:
            raise NotFoundProfileError(profile_id=command.user_id)

        stat = await self.storage_service.get_stat(profile_config.PENDING_AVATAR_BUCKET, command.file_key)
        if stat.size > profile_config.AVATAR_MAX_SIZE:
            raise AvatarSizeError(
                current_size=stat.size
            )

        data = await self.storage_service.download(profile_config.PENDING_AVATAR_BUCKET, command.file_key)
        mime = magic.from_buffer(data, mime=True)

        if mime not in profile_config.AVATAR_ALLOWED_MIMES:
            raise AvatarNotImageTypeError(type_avatar=mime)

        img: pyvips.Image = pyvips.Image.new_from_buffer(data, "", access="random") # type: ignore
        if img.width <= 0 or img.height <= 0 or img.width * img.height > profile_config.AVATAR_MAX_PIXELS: # type: ignore
            raise AvatarSizeError(current_size=img.width * img.height) # type: ignore

        versions = {}

        for s in SizeAvatar:
            thumb = img.thumbnail_image(s, height=s, crop="centre") # type: ignore

            webp = thumb.write_to_buffer(".webp") # type: ignore
            avif = thumb.write_to_buffer(".avif") # type: ignore
            jpg = thumb.write_to_buffer(".jpg") # type: ignore

            key_webp = f"{command.user_id}/{s.value}.webp"
            key_avif = f"{command.user_id}/{s.value}.avif"
            key_jpg = f"{command.user_id}/{s.value}.jpg"

            webp_url = await self.storage_service.upload_file(
                upload_file=UploadFile(
                    bucket_name=profile_config.AVATAR_BUCKET,
                    file_key=key_webp, file_content=io.BytesIO(webp), size=len(webp)
                )
            )
            avif_url = await self.storage_service.upload_file(
                upload_file=UploadFile(
                    bucket_name=profile_config.AVATAR_BUCKET,
                    file_key=key_avif, file_content=io.BytesIO(avif), size=len(avif)
                )
            )
            jpg_url = await self.storage_service.upload_file(
                upload_file=UploadFile(
                    bucket_name=profile_config.AVATAR_BUCKET,
                    file_key=key_jpg, file_content=io.BytesIO(jpg), size=len(jpg)
                )
            )

            versions[s.value] = {"webp": webp_url, "avif": avif_url, "jpg": jpg_url}

        profile.update_avatar(versions)
        await self.event_bus.publish(profile.pull_events())
        await self.session.commit()
        await self.profile_repository.invalidate_cache()

        logger.info(
            "Profile create", extra={
                "user_id": command.user_id
            }
        )
