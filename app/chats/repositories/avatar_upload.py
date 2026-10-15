from dataclasses import dataclass
from uuid import UUID

import orjson
from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.keys import ChatAvatarKeys


@dataclass(frozen=True)
class ChatAvatarUploadSlot:
    upload_token: UUID
    chat_id: UUID
    uploader_id: int
    s3_key: str
    mime_type: str
    file_size: int


@dataclass
class ChatAvatarUploadRepository:
    redis: Redis

    async def save(self, slot: ChatAvatarUploadSlot) -> None:
        await self.redis.set(
            ChatAvatarKeys.upload_slot(str(slot.upload_token)),
            orjson.dumps({
                "chat_id": str(slot.chat_id),
                "uploader_id": slot.uploader_id,
                "s3_key": slot.s3_key,
                "mime_type": slot.mime_type,
                "file_size": slot.file_size,
            }),
            ex=chat_config.CHAT_AVATAR_UPLOAD_TTL,
        )

    async def get(self, upload_token: UUID) -> ChatAvatarUploadSlot | None:
        raw = await self.redis.get(ChatAvatarKeys.upload_slot(str(upload_token)))
        return self._decode(upload_token, raw)

    async def pop(self, upload_token: UUID) -> ChatAvatarUploadSlot | None:
        raw = await self.redis.getdel(ChatAvatarKeys.upload_slot(str(upload_token)))
        return self._decode(upload_token, raw)

    @staticmethod
    def _decode(upload_token: UUID, raw: str | bytes | None) -> ChatAvatarUploadSlot | None:
        if raw is None:
            return None

        data = orjson.loads(raw)
        return ChatAvatarUploadSlot(
            upload_token=upload_token,
            chat_id=UUID(data["chat_id"]),
            uploader_id=int(data["uploader_id"]),
            s3_key=data["s3_key"],
            mime_type=data["mime_type"],
            file_size=int(data["file_size"]),
        )
