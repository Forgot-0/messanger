import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.exceptions import SlowModeLimitError
from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.services.access import ChatAccessService
from app.core.services.storage.service import StorageService

if TYPE_CHECKING:
    from app.chats.dtos.attachments import AttachmentDTO


SCRIPT_SLOW_MODE = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local result = redis.call('SET', key, '1', 'EX', ttl, 'NX')
if result then
    return {1, ttl}
else
    return {0, redis.call('TTL', key)}
end
"""


@dataclass
class MessageService:
    redis: Redis
    access_service: ChatAccessService
    storage_service: StorageService

    async def is_slow(self, chat: Chat, user_id: int, member: ChatMember | None) -> None:
        if chat.slow_mode_seconds <= 0 or self.access_service.can_bypass_slow_mode(member):
            return

        key = f"chat:slowmode:{chat.id}:{user_id}"
        script = self.redis.register_script(SCRIPT_SLOW_MODE)
        allowed, ttl = await script(keys=[key], args=[chat.slow_mode_seconds])

        if allowed:
            return
        raise SlowModeLimitError(chat_id=str(chat.id), retry_after=max(1, int(ttl)))

    @overload
    async def attach_download_urls(
        self, messages: MessageDTO,
    ) -> MessageDTO:
        ...

    @overload
    async def attach_download_urls(
        self, messages: Iterable[MessageDTO],
    ) -> list[MessageDTO]:
        ...

    async def attach_download_urls(self, messages: MessageDTO | Iterable[MessageDTO]) -> MessageDTO | list[MessageDTO]:
        message_list = [messages] if isinstance(messages, MessageDTO) else list(messages)

        attachments_by_key: dict[str, AttachmentDTO] = {}
        profiles: list[ChatProfileDTO] = []

        for message in message_list:
            if message.profile is not None:
                profiles.append(message.profile)

            if message.reply_to is not None and message.reply_to.profile is not None:
                profiles.append(message.reply_to.profile)

            if message.forwarded_from is not None and message.forwarded_from.profile is not None:
                profiles.append(message.forwarded_from.profile)

            for attachment in message.attachments:
                attachments_by_key[attachment.s3_key] = attachment

        await self.attach_profile_urls(profiles)

        if not attachments_by_key:
            return message_list[0] if isinstance(messages, MessageDTO) else message_list

        keys = tuple(attachments_by_key)
        urls = await asyncio.gather(
            *(
                self.get_attachmnent_url_by_key(s3_key=s3_key)
                for s3_key in keys
            )
        )

        for s3_key, url in zip(keys, urls, strict=True):
            attachments_by_key[s3_key].url = url
            attachments_by_key[s3_key].url_expires_in = chat_config.DOWNLOAD_URL_TTL

        return message_list[0] if isinstance(messages, MessageDTO) else message_list

    async def attach_profile_urls(
        self, profiles: Iterable[ChatProfileDTO | None]
    ) -> None:
        by_key: dict[str, list[ChatProfileDTO]] = {}
        for profile in profiles:
            if profile is None or not profile.avatar_s3_key:
                continue
            by_key.setdefault(profile.avatar_s3_key, []).append(profile)

        if not by_key:
            return

        keys = tuple(by_key)
        urls = await asyncio.gather(
            *(self.get_chat_profile_url_by_key(s3_key) for s3_key in keys)
        )
        for s3_key, url in zip(keys, urls, strict=True):
            for profile in by_key[s3_key]:
                profile.avatar_url = url

    async def get_attachmnent_url_by_key(self, s3_key: str) -> str:
        key = f"attachment:{s3_key}"
        url = await self.redis.get(key)
        if url is None:
            url = await self.storage_service.generate_presigned_url(
                bucket_name=chat_config.ATTACHMENT_BUCKET,
                file_key=s3_key,
                expires=chat_config.DOWNLOAD_URL_TTL,
            )
            await self.redis.set(key, url, ex=chat_config.DOWNLOAD_URL_TTL-30)

        return url # pyright: ignore[reportReturnType]

    async def get_chat_profile_url_by_key(self, s3_key: str) -> str:
        key = f"chat:profile:{s3_key}"
        url = await self.redis.get(key)
        if url is None:
            url = await self.storage_service.generate_presigned_url(
                bucket_name=chat_config.AVATAR_BUCKET,
                file_key=s3_key,
                expires=chat_config.DOWNLOAD_URL_TTL,
            )
            await self.redis.set(key, url, ex=chat_config.DOWNLOAD_URL_TTL-30)

        return url # pyright: ignore[reportReturnType]
