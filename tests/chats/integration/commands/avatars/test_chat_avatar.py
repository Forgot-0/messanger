from uuid import uuid4

import httpx
import pytest
import pyvips
from dishka import AsyncContainer

from app.chats.commands.avatars.confirm import (
    ConfirmChatAvatarUploadCommand,
    ConfirmChatAvatarUploadCommandHandler,
)
from app.chats.commands.avatars.process import ProcessChatAvatarCommand, ProcessChatAvatarCommandHandler
from app.chats.commands.avatars.remove import RemoveChatAvatarCommand, RemoveChatAvatarCommandHandler
from app.chats.commands.avatars.request_upload import (
    RequestChatAvatarUploadCommand,
    RequestChatAvatarUploadCommandHandler,
)
from app.chats.config import chat_config
from app.chats.dtos.avatars import ChatAvatarUploadSlotDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    ChatAvatarValidationError,
    InvalidUploadTokenError,
)
from app.chats.models.chat import Chat, UpdatedChatEvent
from app.chats.repositories.chat import ChatRepository
from app.chats.tasks.chat_avatar import ChatAvatarProcessTask
from app.core.services.auth.dto import UserJWTData
from app.core.services.queues.service import QueueService
from app.core.services.storage.exceptions import ObjectNotFoundError
from app.core.services.storage.service import StorageService
from tests.mocks import FakeQueueService, RecordingEventBus


def png_bytes(width: int = 300, height: int = 200) -> bytes:
    return pyvips.Image.black(width, height, bands=3).write_to_buffer(".png")  # type: ignore[no-any-return]


async def object_exists(storage: StorageService, bucket: str, key: str) -> bool:
    try:
        await storage.get_stat(bucket_name=bucket, file_key=key)
    except ObjectNotFoundError:
        return False
    return True


def key_of(storage: StorageService, url: str) -> str:
    return url.removeprefix(storage.get_public_url_object(chat_config.CHAT_AVATAR_BUCKET, ""))


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatAvatarUpload:

    @pytest.fixture
    async def storage(self, request_container: AsyncContainer) -> StorageService:
        return await request_container.get(StorageService)

    @pytest.fixture
    async def request_slot(self, request_container: AsyncContainer, user_jwt: UserJWTData):
        handler = await request_container.get(RequestChatAvatarUploadCommandHandler)

        async def _request(chat: Chat, mime_type: str = "image/png", file_size: int = 10_000) -> ChatAvatarUploadSlotDTO:
            return await handler.handle(RequestChatAvatarUploadCommand(
                user_jwt_data=user_jwt, chat_id=chat.id, mime_type=mime_type, file_size=file_size,
            ))

        return _request

    @pytest.fixture
    async def upload_and_process(self, request_container: AsyncContainer, request_slot, user_jwt: UserJWTData):
        confirm = await request_container.get(ConfirmChatAvatarUploadCommandHandler)
        process = await request_container.get(ProcessChatAvatarCommandHandler)
        queue = await request_container.get(QueueService)
        assert isinstance(queue, FakeQueueService)

        async def _run(chat: Chat, content: bytes) -> ChatAvatarUploadSlotDTO:
            slot = await request_slot(chat, file_size=len(content))
            async with httpx.AsyncClient() as http:
                response = await http.put(slot.upload_url, content=content)
                assert response.status_code == 200, response.text

            await confirm.handle(ConfirmChatAvatarUploadCommand(
                user_jwt_data=user_jwt, chat_id=chat.id, upload_token=slot.upload_token,
            ))
            task, data = queue.pushed[-1]
            assert task is ChatAvatarProcessTask
            await process.handle(ProcessChatAvatarCommand(**data))
            return slot

        return _run

    async def test_full_upload_flow_sets_all_variants(
        self,
        upload_and_process,
        storage: StorageService,
        chat_repository: ChatRepository,
        group_chat: Chat,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        slot = await upload_and_process(group_chat, png_bytes())

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        assert set(chat.avatars) == {str(size) for size in chat_config.CHAT_AVATAR_SIZES}
        for variants in chat.avatars.values():
            assert set(variants) == set(chat_config.CHAT_AVATAR_FORMATS)
        assert chat.avatar_s3_key == chat.avatars["64"]["jpg"]
        assert f"{group_chat.id}/{slot.upload_token}/64.jpg" in chat.avatar_s3_key

        for variants in chat.avatars.values():
            for url in variants.values():
                assert await object_exists(storage, chat_config.CHAT_AVATAR_BUCKET, key_of(storage, url))

        assert not await object_exists(
            storage, chat_config.CHAT_AVATAR_BUCKET_PENDING, f"{group_chat.id}/{slot.upload_token}"
        )
        updated = [e for e in mock_event_bus.of_type(UpdatedChatEvent) if e.avatars]
        assert updated and updated[-1].avatar_s3_key == chat.avatar_s3_key

    async def test_replacing_avatar_deletes_previous_version(
        self,
        upload_and_process,
        storage: StorageService,
        chat_repository: ChatRepository,
        group_chat: Chat,
    ) -> None:
        await upload_and_process(group_chat, png_bytes())
        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        old_key = key_of(storage, chat.avatars["512"]["webp"])

        await upload_and_process(group_chat, png_bytes(400, 400))

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        assert key_of(storage, chat.avatars["512"]["webp"]) != old_key
        assert not await object_exists(storage, chat_config.CHAT_AVATAR_BUCKET, old_key)

    async def test_non_image_is_rejected_and_chat_untouched(
        self,
        upload_and_process,
        storage: StorageService,
        chat_repository: ChatRepository,
        group_chat: Chat,
    ) -> None:
        slot = await upload_and_process(group_chat, b"definitely not a picture\n" * 10)

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        assert chat.avatars == {}
        assert chat.avatar_s3_key is None
        assert not await object_exists(
            storage, chat_config.CHAT_AVATAR_BUCKET_PENDING, f"{group_chat.id}/{slot.upload_token}"
        )

    async def test_remove_avatar(
        self,
        upload_and_process,
        request_container: AsyncContainer,
        storage: StorageService,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await upload_and_process(group_chat, png_bytes())
        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        key = key_of(storage, chat.avatars["32"]["jpg"])

        remove = await request_container.get(RemoveChatAvatarCommandHandler)
        await remove.handle(RemoveChatAvatarCommand(user_jwt_data=user_jwt, chat_id=group_chat.id))

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        assert chat.avatars == {} and chat.avatar_s3_key is None
        assert not await object_exists(storage, chat_config.CHAT_AVATAR_BUCKET, key)

    async def test_slot_validation(self, request_slot, group_chat: Chat) -> None:
        with pytest.raises(ChatAvatarValidationError):
            await request_slot(group_chat, mime_type="image/gif")

        with pytest.raises(ChatAvatarValidationError):
            await request_slot(group_chat, file_size=chat_config.CHAT_AVATAR_MAX_SIZE + 1)

    @pytest.mark.parametrize("mime_type", ["image/heic", "image/heif"])
    async def test_heic_is_converted_by_the_client_not_the_server(
        self, request_slot, group_chat: Chat, mime_type: str,
    ) -> None:
        with pytest.raises(ChatAvatarValidationError):
            await request_slot(group_chat, mime_type=mime_type)

    async def test_member_without_update_right_cannot_upload(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        handler = await request_container.get(RequestChatAvatarUploadCommandHandler)

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(RequestChatAvatarUploadCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id,
                mime_type="image/png", file_size=100,
            ))

    async def test_confirm_rejects_foreign_or_unknown_token(
        self,
        request_slot,
        request_container: AsyncContainer,
        group_chat: Chat,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        confirm = await request_container.get(ConfirmChatAvatarUploadCommandHandler)
        slot = await request_slot(group_chat)

        with pytest.raises(InvalidUploadTokenError):
            await confirm.handle(ConfirmChatAvatarUploadCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, upload_token=slot.upload_token,
            ))

        with pytest.raises(InvalidUploadTokenError):
            await confirm.handle(ConfirmChatAvatarUploadCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, upload_token=uuid4(),
            ))
