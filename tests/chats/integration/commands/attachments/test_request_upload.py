from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.attachments.request_upload import (
    RequestAttachmentUploadCommand,
    RequestAttachmentUploadCommandHandler,
    UploadRequest,
)
from app.chats.config import chat_config
from app.chats.exceptions import (
    AccessDeniedChatError,
    AttachmentLimitExceededError,
    AttachmentValidationError,
    EmptyAttachmentUploadRequestError,
    NotChatMemberError,
    NotFoundChatError,
)
from app.chats.models.attachment import AttachmentStatus, AttachmentType
from app.chats.models.chat import Chat
from app.chats.repositories.attachment import AttachmentRepository
from app.core.services.auth.dto import UserJWTData
from tests.support.http import assert_presigned_url


def upload(
    *,
    filename: str = "photo.jpg",
    mime_type: str = "image/jpeg",
    file_size: int = 1024,
    attachment_type: AttachmentType | None = None,
) -> UploadRequest:
    return UploadRequest(
        filename=filename,
        mime_type=mime_type,
        file_size=file_size,
        attachment_type=attachment_type,
    )


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestRequestAttachmentUpload:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> RequestAttachmentUploadCommandHandler:
        return await request_container.get(RequestAttachmentUploadCommandHandler)

    @pytest.fixture
    async def attachment_repository(
        self, request_container: AsyncContainer
    ) -> AttachmentRepository:
        return await request_container.get(AttachmentRepository)

    @staticmethod
    def command(chat: Chat, jwt: UserJWTData, *uploads: UploadRequest):
        return RequestAttachmentUploadCommand(
            user_jwt_data=jwt, chat_id=chat.id, uploads=list(uploads)
        )

    async def test_slot_is_created_with_a_presigned_url_and_pending_status(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        attachment_repository: AttachmentRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        slots = await handler.handle(self.command(group_chat, user_jwt, upload()))

        assert len(slots) == 1
        slot = slots[0]
        assert slot.attachment_type == AttachmentType.IMAGE
        assert_presigned_url(
            slot.upload_url,
            bucket=chat_config.ATTACHMENT_BUCKET_PENDING,
            file_key="photo.jpg",
        )
        assert slot.expires_in == chat_config.ATTACHMENT_UPLOAD_TOKEN_TTL

        stored = await attachment_repository.get_by_ids([slot.upload_token])
        assert len(stored) == 1
        assert stored[0].attachment_status == AttachmentStatus.PENDING
        assert stored[0].uploader_id == int(user_jwt.id)

    @pytest.mark.parametrize(
        "mime_type,expected",
        [
            ("image/png", AttachmentType.IMAGE),
            ("image/webp", AttachmentType.IMAGE),
            ("video/mp4", AttachmentType.VIDEO),
            ("application/pdf", AttachmentType.FILE),
            ("text/csv", AttachmentType.FILE),
        ],
    )
    async def test_attachment_type_is_derived_from_the_mime(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mime_type: str,
        expected: AttachmentType,
    ) -> None:
        slots = await handler.handle(
            self.command(group_chat, user_jwt, upload(mime_type=mime_type))
        )

        assert slots[0].attachment_type == expected

    async def test_s3_key_is_scoped_to_the_chat_and_sanitised(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        attachment_repository: AttachmentRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        slots = await handler.handle(
            self.command(group_chat, user_jwt, upload(filename="../../etc/passwd.png"))
        )

        stored = await attachment_repository.get_by_ids([slots[0].upload_token])
        key = stored[0].s3_key

        assert key.startswith(f"chats/{group_chat.id}/")
        assert len(key.split("/")) == 4

    async def test_several_media_get_separate_slots(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        slots = await handler.handle(
            self.command(
                group_chat, user_jwt, upload(), upload(mime_type="video/mp4"), upload()
            )
        )

        assert len(slots) == 3
        assert len({s.upload_token for s in slots}) == 3

    async def test_disallowed_mime_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AttachmentValidationError):
            await handler.handle(
                self.command(
                    group_chat, user_jwt, upload(mime_type="application/x-executable")
                )
            )

    async def test_voice_with_a_non_voice_mime_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AttachmentValidationError):
            await handler.handle(
                self.command(
                    group_chat,
                    user_jwt,
                    upload(mime_type="image/jpeg", attachment_type=AttachmentType.VOICE),
                )
            )

    async def test_video_note_with_a_non_video_mime_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AttachmentValidationError):
            await handler.handle(
                self.command(
                    group_chat,
                    user_jwt,
                    upload(
                        mime_type="audio/ogg", attachment_type=AttachmentType.VIDEO_NOTE
                    ),
                )
            )

    @pytest.mark.parametrize(
        "mime_type,limit_name",
        [
            ("image/jpeg", "MAX_MEDIA_SIZE"),
            ("video/mp4", "MAX_MEDIA_SIZE"),
            ("application/pdf", "MAX_FILE_SIZE"),
        ],
    )
    async def test_oversized_upload_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mime_type: str,
        limit_name: str,
    ) -> None:
        limit = getattr(chat_config, limit_name)

        with pytest.raises(AttachmentValidationError):
            await handler.handle(
                self.command(
                    group_chat, user_jwt, upload(mime_type=mime_type, file_size=limit + 1)
                )
            )

    async def test_oversized_voice_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AttachmentValidationError):
            await handler.handle(
                self.command(
                    group_chat,
                    user_jwt,
                    upload(
                        mime_type="audio/ogg",
                        attachment_type=AttachmentType.VOICE,
                        file_size=chat_config.MAX_VOICE_SIZE + 1,
                    ),
                )
            )

    async def test_oversized_video_note_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AttachmentValidationError):
            await handler.handle(
                self.command(
                    group_chat,
                    user_jwt,
                    upload(
                        mime_type="video/mp4",
                        attachment_type=AttachmentType.VIDEO_NOTE,
                        file_size=chat_config.MAX_VIDEO_NOTE_SIZE + 1,
                    ),
                )
            )

    async def test_too_many_media_in_one_request(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        uploads = [upload() for _ in range(chat_config.MAX_MEDIA_PER_MESSAGE + 1)]

        with pytest.raises(AttachmentLimitExceededError):
            await handler.handle(self.command(group_chat, user_jwt, *uploads))

    async def test_too_many_files_in_one_request(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        uploads = [
            upload(mime_type="application/pdf")
            for _ in range(chat_config.MAX_FILES_PER_MESSAGE + 1)
        ]

        with pytest.raises(AttachmentLimitExceededError):
            await handler.handle(self.command(group_chat, user_jwt, *uploads))

    async def test_two_exclusive_attachments_are_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        voice = upload(mime_type="audio/ogg", attachment_type=AttachmentType.VOICE)
        note = upload(mime_type="video/mp4", attachment_type=AttachmentType.VIDEO_NOTE)

        with pytest.raises(AttachmentLimitExceededError):
            await handler.handle(self.command(group_chat, user_jwt, voice, note))

    async def test_exclusive_attachment_cannot_travel_with_media(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        voice = upload(mime_type="audio/ogg", attachment_type=AttachmentType.VOICE)

        with pytest.raises(AttachmentLimitExceededError):
            await handler.handle(self.command(group_chat, user_jwt, voice, upload()))

    async def test_single_voice_alone_is_allowed(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        slots = await handler.handle(
            self.command(
                group_chat,
                user_jwt,
                upload(mime_type="audio/ogg", attachment_type=AttachmentType.VOICE),
            )
        )

        assert [s.attachment_type for s in slots] == [AttachmentType.VOICE]

    async def test_empty_request_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(EmptyAttachmentUploadRequestError):
            await handler.handle(self.command(group_chat, user_jwt))

    async def test_outsider_is_not_a_member(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await handler.handle(
                self.command(group_chat, make_user_jwt(id="99"), upload())
            )

    async def test_missing_chat_is_rejected(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                RequestAttachmentUploadCommand(
                    user_jwt_data=user_jwt, chat_id=uuid4(), uploads=[upload()]
                )
            )

    async def test_member_without_send_permission_is_denied(
        self,
        handler: RequestAttachmentUploadCommandHandler,
        create_group_chat,
        make_user_jwt,
    ) -> None:
        chat = await create_group_chat([2, 3], 0, admin_only=True)

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                self.command(chat, make_user_jwt(id="2"), upload())
            )
