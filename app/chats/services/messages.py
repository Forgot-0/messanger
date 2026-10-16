import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, overload

from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.exceptions import SlowModeLimitError
from app.chats.keys import AttachmentKeys
from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.services.access import ChatAccessService
from app.core.services.storage.service import StorageService

if TYPE_CHECKING:
    from app.chats.dtos.attachments import AttachmentDTO


class AvatarHolder(Protocol):
    avatar_s3_key: str | None
    avatar_url: str | None


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

        attachments: list[AttachmentDTO] = []
        for message in message_list:
            attachments.extend(message.attachments)
            for nested in (message.reply_to, message.forwarded_from):
                if nested is not None:
                    attachments.extend(nested.attachments)

        await self.image_urls(self.message_profiles(message_list))
        await self.attach_attachment_urls(attachments)

        return message_list[0] if isinstance(messages, MessageDTO) else message_list

    async def attach_attachment_urls(self, attachments: Iterable[AttachmentDTO]) -> None:
        items = list(attachments)
        if not items:
            return

        keys = [item.s3_key for item in items]
        keys.extend(preview.s3_key for item in items for preview in item.previews)
        urls = await self.presigned_attachment_urls(keys)

        for item in items:
            item.url = urls.get(item.s3_key)
            item.url_expires_in = chat_config.DOWNLOAD_URL_TTL
            for preview in item.previews:
                preview.url = urls.get(preview.s3_key)
                preview.url_expires_in = chat_config.DOWNLOAD_URL_TTL

    async def presigned_attachment_urls(self, keys: Iterable[str]) -> dict[str, str]:
        unique = list(dict.fromkeys(key for key in keys if key))
        urls = {key: key for key in unique if "http" in key}
        pending = [key for key in unique if key not in urls]
        if not pending:
            return urls

        cached = await self.redis.mget([AttachmentKeys.download_url(key) for key in pending])
        missing: list[str] = []
        for key, url in zip(pending, cached, strict=True):
            if url is None:
                missing.append(key)
            else:
                urls[key] = str(url)

        if missing:
            signed = await asyncio.gather(*(
                self.storage_service.generate_presigned_url(
                    bucket_name=chat_config.ATTACHMENT_BUCKET,
                    file_key=key,
                    expires=chat_config.DOWNLOAD_URL_TTL,
                )
                for key in missing
            ))
            async with self.redis.pipeline(transaction=False) as pipe:
                for key, url in zip(missing, signed, strict=True):
                    pipe.set(AttachmentKeys.download_url(key), url, ex=chat_config.DOWNLOAD_URL_TTL - 30)
                await pipe.execute()
            urls.update(zip(missing, signed, strict=True))

        return urls

    @staticmethod
    def message_profiles(messages: Iterable[MessageDTO]) -> list[ChatProfileDTO]:
        profiles: list[ChatProfileDTO] = []
        for message in messages:
            if message.profile is not None:
                profiles.append(message.profile)

            if message.reply_to is not None and message.reply_to.profile is not None:
                profiles.append(message.reply_to.profile)

            if message.forwarded_from is not None and message.forwarded_from.profile is not None:
                profiles.append(message.forwarded_from.profile)

        return profiles

    async def image_urls(
        self, profiles: Iterable[AvatarHolder | None]
    ) -> None:
        by_key: dict[str, list[AvatarHolder]] = {}
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

    async def get_chat_profile_url_by_key(self, s3_key: str) -> str:
        if "http" in s3_key:
            return s3_key

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
