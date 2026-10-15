from uuid import UUID, uuid4

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.dtos.attachments import SharedMediaDTO, SharedMediaType
from app.chats.exceptions import NotChatMemberError
from app.chats.models.attachment import AttachmentType, HlsStatus, MessageAttachment
from app.chats.models.chat import Chat
from app.chats.models.message import Message, MessageType
from app.chats.queries.attachments.get_shared_media import GetSharedMediaQuery, GetSharedMediaQueryHandler
from app.core.services.auth.dto import UserJWTData
from tests.support.http import assert_presigned_url


def attachment(chat: Chat, kind: AttachmentType, *, name: str = "file") -> MessageAttachment:
    item = MessageAttachment.create(
        chat_id=chat.id, uploader_id=1, attachment_type=kind,
        s3_key=f"chats/{chat.id}/{uuid4()}/{name}", mime_type="application/octet-stream",
        original_filename=name, size=1,
    )
    item.mark_proccesed()
    return item


class History:
    """Сообщения чата с нарастающим seq, как их пишет send-хендлер."""

    def __init__(self, db_session: AsyncSession, chat: Chat) -> None:
        self.db_session = db_session
        self.chat = chat
        self.seq = 0

    async def send(
        self,
        *kinds: AttachmentType,
        content: str | None = None,
        message_type: MessageType = MessageType.IMAGE,
        deleted: bool = False,
    ) -> tuple[Message, list[MessageAttachment]]:
        self.seq += 1
        items = [attachment(self.chat, kind, name=f"{kind.value}-{self.seq}") for kind in kinds]
        message = Message.create(
            sender_id=1, chat_id=self.chat.id, seq=self.seq, content=content,
            message_type=message_type if kinds else MessageType.TEXT,
            attachments=items or None,
        )
        if deleted:
            message.delete(deleted_by=1)
        self.db_session.add(message)
        await self.db_session.commit()
        return message, items


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSharedMedia:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> GetSharedMediaQueryHandler:
        return await request_container.get(GetSharedMediaQueryHandler)

    @pytest.fixture
    def history(self, db_session: AsyncSession, group_chat: Chat) -> History:
        return History(db_session, group_chat)

    async def _page(
        self,
        handler: GetSharedMediaQueryHandler,
        chat: Chat,
        user: UserJWTData,
        media_type: SharedMediaType,
        *,
        limit: int = 30,
        cursor: str | None = None,
    ) -> SharedMediaDTO:
        return await handler.handle(
            GetSharedMediaQuery(user_jwt_data=user, chat_id=chat.id, media_type=media_type, limit=limit, cursor=cursor)
        )

    @staticmethod
    def _attachment_ids(page: SharedMediaDTO) -> list[UUID]:
        return [item.attachment.id for item in page.items if item.attachment is not None]

    async def test_tabs_are_split_by_type_newest_first(
        self, handler, history, group_chat, user_jwt,
    ) -> None:
        _, album = await history.send(AttachmentType.IMAGE, AttachmentType.IMAGE, AttachmentType.VIDEO)
        _, (document,) = await history.send(AttachmentType.FILE, message_type=MessageType.FILE)
        _, (voice,) = await history.send(AttachmentType.VOICE, message_type=MessageType.VOICE)
        _, (note,) = await history.send(AttachmentType.VIDEO_NOTE, message_type=MessageType.VIDEO_NOTE)
        _, (photo,) = await history.send(AttachmentType.IMAGE, content="caption")
        await history.send(AttachmentType.IMAGE, deleted=True)
        link_message, _ = await history.send(content="read https://example.com")
        await history.send(content="plain")

        photos = await self._page(handler, group_chat, user_jwt, SharedMediaType.PHOTO)
        media = await self._page(handler, group_chat, user_jwt, SharedMediaType.MEDIA)
        files = await self._page(handler, group_chat, user_jwt, SharedMediaType.FILE)
        voices = await self._page(handler, group_chat, user_jwt, SharedMediaType.VOICE)
        links = await self._page(handler, group_chat, user_jwt, SharedMediaType.LINK)

        assert self._attachment_ids(photos) == [photo.id, album[1].id, album[0].id]
        assert photos.items[0].content == "caption"
        assert self._attachment_ids(media) == [photo.id, album[2].id, album[1].id, album[0].id]
        assert self._attachment_ids(files) == [document.id]
        assert self._attachment_ids(voices) == [note.id, voice.id]
        assert [(item.message_id, item.attachment) for item in links.items] == [(link_message.id, None)]
        assert not photos.has_next and photos.next_cursor is None

    async def test_cursor_walks_through_an_album_without_gaps(
        self, handler, history, group_chat, user_jwt,
    ) -> None:
        _, first = await history.send(AttachmentType.IMAGE)
        _, album = await history.send(*[AttachmentType.IMAGE] * 5)
        _, last = await history.send(AttachmentType.IMAGE)
        expected = [last[0].id, *[item.id for item in reversed(album)], first[0].id]

        seen: list[UUID] = []
        cursor: str | None = None
        for _ in range(10):
            page = await self._page(handler, group_chat, user_jwt, SharedMediaType.PHOTO, limit=3, cursor=cursor)
            seen.extend(self._attachment_ids(page))
            if not page.has_next:
                break
            cursor = page.next_cursor

        assert seen == expected

    async def test_link_tab_pages_by_seq(self, handler, history, group_chat, user_jwt) -> None:
        sent = [await history.send(content=f"www.example.com/{n}") for n in range(3)]

        first = await self._page(handler, group_chat, user_jwt, SharedMediaType.LINK, limit=2)
        second = await self._page(
            handler, group_chat, user_jwt, SharedMediaType.LINK, limit=2, cursor=first.next_cursor
        )

        assert first.next_cursor == str(sent[1][0].seq)
        assert [item.message_id for item in first.items + second.items] == [m.id for m, _ in reversed(sent)]
        assert not second.has_next

    async def test_items_carry_signed_links_for_the_original_and_previews(
        self, handler, history, group_chat, user_jwt, db_session,
    ) -> None:
        _, (video,) = await history.send(AttachmentType.VIDEO)
        video.previews = [{
            "size": 320, "width": 320, "height": 180, "mime_type": "image/webp", "file_size": 10,
            "s3_key": f"media/{group_chat.id}/{video.id}/previews/320.webp",
        }]
        video.thumbhash = "1QcSHQRnh493V4dIh4eXh1h4kJUI"
        video.hls_status = HlsStatus.READY
        video.hls_key = f"media/{group_chat.id}/{video.id}/hls/master.m3u8"
        await db_session.commit()

        (item,) = (await self._page(handler, group_chat, user_jwt, SharedMediaType.VIDEO)).items

        assert item.attachment is not None
        assert_presigned_url(item.attachment.url or "", bucket=chat_config.ATTACHMENT_BUCKET, file_key=video.s3_key)
        (preview,) = item.attachment.previews
        assert_presigned_url(preview.url or "", bucket=chat_config.ATTACHMENT_BUCKET, file_key="320.webp")
        assert item.attachment.thumbhash == "1QcSHQRnh493V4dIh4eXh1h4kJUI"
        assert item.attachment.hls_url is not None
        assert item.attachment.hls_url.endswith("/master.m3u8")
        assert "hls_key" not in item.attachment.model_dump()

    async def test_other_chats_media_does_not_leak_in(
        self, handler, history, group_chat, user_jwt, db_session,
    ) -> None:
        other = Chat.create(created_by=1, members_ids=[], chat_type=group_chat.type, name="Other", is_public=False)
        db_session.add(other)
        await db_session.commit()
        await History(db_session, other).send(AttachmentType.IMAGE)

        page = await self._page(handler, group_chat, user_jwt, SharedMediaType.PHOTO)

        assert page.items == []

    async def test_outsider_cannot_list_the_media(self, handler, group_chat, make_user_jwt) -> None:
        with pytest.raises(NotChatMemberError):
            await self._page(handler, group_chat, make_user_jwt(id="999"), SharedMediaType.PHOTO)
