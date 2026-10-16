from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.attachments import (
    SHARED_MEDIA_ATTACHMENT_TYPES,
    AttachmentDTO,
    SharedMediaDTO,
    SharedMediaItemDTO,
    SharedMediaType,
)
from app.chats.exceptions import NotChatMemberError
from app.chats.models.message import Message
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.services.messages import MessageService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData

ZERO_UUID = UUID(int=0)


def parse_cursor(cursor: str | None) -> tuple[int, UUID] | None:
    if cursor is None:
        return None

    raw_seq, _, raw_id = cursor.partition(":")
    return int(raw_seq), (UUID(raw_id) if raw_id else ZERO_UUID)


@dataclass(frozen=True, kw_only=True)
class GetSharedMediaQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    media_type: SharedMediaType
    limit: int = chat_config.SHARED_MEDIA_PAGE_SIZE
    cursor: str | None = None


@dataclass(frozen=True)
class GetSharedMediaQueryHandler(BaseQueryHandler[GetSharedMediaQuery, SharedMediaDTO]):
    chat_repository: ChatRepository
    attachment_repository: AttachmentRepository
    message_repository: MessageRepository
    message_service: MessageService

    async def handle(self, query: GetSharedMediaQuery) -> SharedMediaDTO:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id, with_role=False)
        if member is None or member.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        limit = min(max(query.limit, 1), chat_config.SHARED_MEDIA_MAX_PAGE_SIZE)
        before = parse_cursor(query.cursor)

        if query.media_type == SharedMediaType.LINK:
            messages = await self.message_repository.get_link_messages_page(
                        query.chat_id, limit + 1, before_seq=before[0] if before else None
                    )
            link_page = messages[:limit]
            has_next = len(messages) > limit
            return SharedMediaDTO(
                items=[self._item(message) for message in link_page],
                has_next=has_next,
                next_cursor=str(link_page[-1].seq) if has_next and link_page else None,
            )


        rows = await self.attachment_repository.get_shared_media_page(
            query.chat_id, SHARED_MEDIA_ATTACHMENT_TYPES[query.media_type], limit + 1, before
        )
        page = rows[:limit]
        has_next = len(rows) > limit

        attachments = [AttachmentDTO.model_validate(attachment) for attachment, _ in page]
        await self.message_service.attach_attachment_urls(attachments)

        last = page[-1][0] if page else None
        return SharedMediaDTO(
            items=[
                self._item(message, attachment)
                for attachment, (_, message) in zip(attachments, page, strict=True)
            ],
            has_next=has_next,
            next_cursor=f"{last.message_seq}:{last.id}" if has_next and last else None,
        )

    @staticmethod
    def _item(message: Message, attachment: AttachmentDTO | None = None) -> SharedMediaItemDTO:
        return SharedMediaItemDTO(
            message_id=message.id,
            message_seq=message.seq,
            author_id=message.author_id,
            content=message.content,
            created_at=message.created_at,
            attachment=attachment,
        )
