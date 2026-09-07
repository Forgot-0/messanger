import logging
from dataclasses import dataclass
from uuid import UUID

import magic
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.exceptions import AccessDeniedChatError, AttachmentMediaValidationError
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.schemas.ws import AttachmentSuccessPayload, WSEventType
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.media.exceptions import MediaProbeUnavailableError
from app.core.services.storage.exceptions import StorageError
from app.core.services.storage.service import StorageService
from app.core.websocket.dtos import DeliveryData, DeliveryDTO
from app.core.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)

MAGIC_HEADER_BYTES = 1024


@dataclass(frozen=True)
class ProccessAttachmentsCommand(BaseCommand):
    chat_id: str
    user_id: int
    upload_tokens: list[str]


@dataclass(frozen=True)
class ProccessAttachmentsCommandHandler(BaseCommandHandler[ProccessAttachmentsCommand, None]):
    attachment_repository: AttachmentRepository
    storage_service: StorageService
    connection_manager: ConnectionManager
    session: AsyncSession
    media_validator: AttachmentMediaValidator

    async def handle(self, command: ProccessAttachmentsCommand) -> None:
        slots = await self.attachment_repository.get_by_ids(
            [UUID(attachment_id) for attachment_id in command.upload_tokens]
        )

        failed_tokens: list[str] = []
        for slot in slots:
            try:
                if slot.uploader_id != command.user_id:
                    raise AccessDeniedChatError(chat_id=str(slot.chat_id), requester_id=command.user_id)

                stat = await self.storage_service.get_stat(
                    bucket_name=chat_config.ATTACHMENT_BUCKET_PENDING,
                    file_key=slot.s3_key,
                )
                if stat.size <= 0 or stat.size > slot.size:
                    logger.warning(
                        "Attachment size validation failed",
                        extra={"slot_id": str(slot.id), "size": stat.size, "limit": slot.size},
                    )
                    slot.mark_error()
                    failed_tokens.append(str(slot.id))
                    continue

                data = await self.storage_service.download_range(
                    bucket_name=chat_config.ATTACHMENT_BUCKET_PENDING,
                    file_key=slot.s3_key,
                    offset=0,
                    length=MAGIC_HEADER_BYTES,
                )
                mime_type = magic.from_buffer(data, mime=True)

                if mime_type != slot.mime_type:
                    logger.error(
                        "MIME mismatch for attachment",
                        extra={
                            "slot_id": str(slot.id),
                            "declared": slot.mime_type,
                            "detected": mime_type,
                        },
                    )
                    slot.mark_error()
                    failed_tokens.append(str(slot.id))
                    continue

                if self.media_validator.requires_probe(slot.attachment_type):
                    media_info = await self.media_validator.validate_and_apply(slot, stat)

                    logger.info(
                        "Media attachment validated",
                        extra={
                            "slot_id": str(slot.id),
                            "attachment_type": slot.attachment_type.value,
                            "detected_mime": mime_type,
                            "duration": slot.duration_seconds,
                            "width": slot.width,
                            "height": slot.height,
                            "probed_duration": round(media_info.duration, 3),
                        },
                    )

                await self.storage_service.copy_object(
                    bucket_from=chat_config.ATTACHMENT_BUCKET_PENDING,
                    file_key_from=slot.s3_key,
                    bucket_to=chat_config.ATTACHMENT_BUCKET,
                    file_key_to=slot.s3_key,
                )
                await self.storage_service.delete_file(
                    bucket_name=chat_config.ATTACHMENT_BUCKET_PENDING,
                    file_key=slot.s3_key,
                )
                slot.mark_proccesed()

            except AttachmentMediaValidationError as exc:
                logger.warning(
                    "Attachment rejected by media validation",
                    extra={
                        "slot_id": str(slot.id),
                        "attachment_type": slot.attachment_type.value,
                        "reason": exc.reason.value,
                        "limit": exc.limit,
                        "detected": exc.detected,
                        "error_class": "permanent",
                    },
                )
                slot.mark_error()
                failed_tokens.append(str(slot.id))

            except (StorageError, MediaProbeUnavailableError):
                logger.exception(
                    "Attachment processing failed due to infrastructure error",
                    extra={
                        "slot_id": str(slot.id),
                        "attachment_type": slot.attachment_type.value,
                        "error_class": "transient",
                    },
                )
                slot.mark_error()
                failed_tokens.append(str(slot.id))

            except Exception:
                logger.exception(
                    "Processing failed for attachment",
                    extra={"slot_id": str(slot.id)},
                )
                slot.mark_error()
                failed_tokens.append(str(slot.id))

        await self.session.commit()

        try:
            successful_tokens = [t for t in command.upload_tokens if t not in failed_tokens]
            if successful_tokens:
                await self.connection_manager.send_user_payload(
                    event=DeliveryDTO(
                        type=WSEventType.ATTACHMENT_SUCCESS,
                        channel=command.chat_id,
                        payload=AttachmentSuccessPayload(
                            user_id=command.user_id,
                            chat_id=command.chat_id,
                            tokens=successful_tokens,
                        ).model_dump(),
                        delivery=DeliveryData(
                            require_subscription=False,
                            recipients=[command.user_id],
                        ),
                        ts=slot.created_at.isoformat()
                    )
                )
            if failed_tokens:
                logger.warning(
                    "Attachment processing failed for some tokens",
                    extra={"user_id": command.user_id, "chat_id": command.chat_id, "failed": failed_tokens},
                )
        except Exception:
            logger.exception("Failed to notify user of upload results")
