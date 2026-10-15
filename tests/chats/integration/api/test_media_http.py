from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.models.attachment import AttachmentType, HlsStatus, MessageAttachment
from app.chats.models.message import Message, MessageType
from app.chats.services.hls import HlsUrlSigner, master_playlist, plan_renditions
from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.aioboto.client import S3Client
from tests.chats.integration.factories import group_chat_payload
from tests.support.http import api_path, assert_presigned_url

VARIANT = (
    "#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:4\n#EXT-X-PLAYLIST-TYPE:VOD\n"
    '#EXT-X-MAP:URI="v0.mp4",BYTERANGE="1372@0"\n'
    "#EXTINF:4.000000,\n#EXT-X-BYTERANGE:227155@1372\nv0.mp4\n#EXT-X-ENDLIST\n"
)


async def create_chat(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(api_path("chats/"), json=group_chat_payload(name="Media"), headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


async def ready_video(db_session: AsyncSession, s3_test_client: S3Client, chat_id: str) -> tuple[Message, MessageAttachment]:
    video = MessageAttachment.create(
        chat_id=UUID(chat_id), uploader_id=1, attachment_type=AttachmentType.VIDEO,
        s3_key=f"chats/{chat_id}/{uuid4()}/clip.mp4", mime_type="video/mp4",
        original_filename="clip.mp4", size=1,
    )
    video.mark_proccesed()
    hls_dir = f"media/{chat_id}/{video.id}/hls"
    video.hls_status = HlsStatus.READY
    video.hls_key = f"{hls_dir}/master.m3u8"
    message = Message.create(
        sender_id=1, chat_id=UUID(chat_id), seq=1, content=None,
        message_type=MessageType.IMAGE, attachments=[video],
    )
    db_session.add(message)
    await db_session.commit()

    for name, body in (
        ("master.m3u8", master_playlist(plan_renditions(1280, 720)[:1], has_audio=True)),
        ("v0.m3u8", VARIANT),
    ):
        await s3_test_client.put_object(Bucket=chat_config.ATTACHMENT_BUCKET, Key=f"{hls_dir}/{name}", Body=body.encode())
    return message, video


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSharedMediaHttp:

    async def test_empty_chat_has_an_empty_tab(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_chat(client, headers)

        response = await client.get(api_path(f"chats/{chat_id}/media/"), params={"type": "photo"}, headers=headers)

        assert response.status_code == 200
        assert response.json() == {"items": [], "has_next": False, "next_cursor": None}

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"type": "gif"},
            {"type": "photo", "limit": 0},
            {"type": "photo", "limit": chat_config.SHARED_MEDIA_MAX_PAGE_SIZE + 1},
            {"type": "photo", "cursor": "abc"},
            {"type": "photo", "cursor": "12:not-a-uuid"},
        ],
    )
    async def test_bad_parameters_are_rejected(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers, params: dict[str, object],
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_chat(client, headers)

        response = await client.get(api_path(f"chats/{chat_id}/media/"), params=params, headers=headers)

        assert response.status_code == 422

    async def test_outsider_gets_not_a_member(
        self, client: AsyncClient, user_jwt: UserJWTData, make_user_jwt, create_auth_headers,
    ) -> None:
        chat_id = await create_chat(client, create_auth_headers(user_jwt))

        response = await client.get(
            api_path(f"chats/{chat_id}/media/"),
            params={"type": "link"},
            headers=create_auth_headers(make_user_jwt(id="999")),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_CHAT_MEMBER"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestHlsPlaylistHttp:

    async def test_master_and_variant_are_served_by_the_signed_link(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
        db_session: AsyncSession, s3_test_client: S3Client,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_chat(client, headers)
        message, video = await ready_video(db_session, s3_test_client, chat_id)

        download = await client.get(
            api_path(f"chats/{chat_id}/messages/{message.id}/attachments/{video.id}/download-url/"),
            headers=headers,
        )
        assert download.status_code == 200
        master_url = download.json()["hls_url"]
        assert master_url.startswith(api_path("chats/media/hls/")) and master_url.endswith("/master.m3u8")

        master = await client.get(master_url)
        assert master.status_code == 200
        assert master.headers["content-type"].startswith("application/vnd.apple.mpegurl")
        assert "\nv0.m3u8\n" in master.text

        variant = await client.get(master_url.rsplit("/", 1)[0] + "/v0.m3u8")
        assert variant.status_code == 200
        media_lines = [line for line in variant.text.splitlines() if not line.startswith("#")]
        assert len(media_lines) == 1
        assert_presigned_url(media_lines[0], bucket=chat_config.ATTACHMENT_BUCKET, file_key="v0.mp4")
        assert f'URI="{media_lines[0]}",BYTERANGE="1372@0"' in variant.text

    async def test_forged_token_is_not_found(self, client: AsyncClient) -> None:
        forged = HlsUrlSigner(secret=b"x" * 32, base_url="", ttl=7_200, ttl_bucket=3_600)

        response = await client.get(forged.url("media/a/b/hls/master.m3u8"))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "HLS_PLAYLIST_NOT_FOUND"

    async def test_signed_link_to_a_missing_stream_is_not_found(self, client: AsyncClient) -> None:
        response = await client.get(HlsUrlSigner.from_config().url(f"media/{uuid4()}/{uuid4()}/hls/master.m3u8"))

        assert response.status_code == 404
