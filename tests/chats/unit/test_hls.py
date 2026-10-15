from dataclasses import dataclass, field

import pytest

from app.chats.config import chat_config
from app.chats.exceptions import HlsPlaylistNotFoundError
from app.chats.services.hls import (
    HlsPlaylistService,
    HlsUrlSigner,
    hls_eligible,
    master_playlist,
    plan_renditions,
)
from tests.mocks import FakeStorageService

HLS_DIR = "media/chat/attachment/hls"


def signer(**overrides: object) -> HlsUrlSigner:
    params: dict[str, object] = {
        "secret": b"s" * 32, "base_url": "https://api.test", "ttl": 7_200, "ttl_bucket": 3_600,
    }
    params.update(overrides)
    return HlsUrlSigner(**params)  # type: ignore[arg-type]


@dataclass
class RecordingStorage(FakeStorageService):
    presigned: list[str] = field(default_factory=list)

    async def generate_presigned_url(self, bucket_name: str, file_key: str, expires: int = 3600) -> str:
        self.presigned.append(file_key)
        return f"https://storage.test/{bucket_name}/{file_key}?sig=1&expires={expires}"


@pytest.mark.unit
@pytest.mark.chats
class TestRenditionPlan:

    def test_landscape_full_hd_gets_the_whole_ladder(self) -> None:
        renditions = plan_renditions(1920, 1080)

        assert [(r.width, r.height) for r in renditions] == [(640, 360), (1280, 720), (1920, 1080)]
        assert [r.name for r in renditions] == ["v0", "v1", "v2"]

    def test_portrait_is_laddered_by_its_short_side(self) -> None:
        renditions = plan_renditions(1080, 1920)

        assert [(r.width, r.height) for r in renditions] == [(360, 640), (720, 1280), (1080, 1920)]

    def test_small_source_is_never_upscaled(self) -> None:
        (only,) = plan_renditions(320, 240)

        assert (only.width, only.height) == (320, 240)
        assert only.video_kbps == min(chat_config.VIDEO_HLS_RENDITIONS.values())

    def test_dimensions_are_even_for_yuv420(self) -> None:
        for rendition in plan_renditions(1279, 721):
            assert rendition.width % 2 == 0 and rendition.height % 2 == 0

    @pytest.mark.parametrize(
        "width,height,duration,expected",
        [
            (1920, 1080, 60, True),
            (None, 1080, 60, False),
            (8192, 4320, 60, False),
            (1920, 1080, chat_config.VIDEO_TRANSCODE_MAX_DURATION_SECONDS + 1, False),
        ],
    )
    def test_eligibility(self, width: int | None, height: int, duration: int, expected: bool) -> None:
        assert hls_eligible(width, height, duration) is expected

    def test_master_lists_renditions_by_bandwidth(self) -> None:
        playlist = master_playlist(plan_renditions(1280, 720), has_audio=True)

        assert playlist.splitlines() == [
            "#EXTM3U",
            "#EXT-X-VERSION:7",
            "#EXT-X-INDEPENDENT-SEGMENTS",
            "#EXT-X-STREAM-INF:BANDWIDTH=928000,RESOLUTION=640x360",
            "v0.m3u8",
            "#EXT-X-STREAM-INF:BANDWIDTH=2628000,RESOLUTION=1280x720",
            "v1.m3u8",
        ]


@pytest.mark.unit
@pytest.mark.chats
class TestUrlSigner:

    def test_url_points_at_the_playlist_route(self) -> None:
        url = signer().url(f"{HLS_DIR}/master.m3u8", now=1_000)

        assert url.startswith("https://api.test/api/v1/chats/media/hls/")
        assert url.endswith("/master.m3u8")

    def test_token_round_trips_to_the_directory(self) -> None:
        token = signer().sign(HLS_DIR, now=1_000)

        assert signer().verify(token, now=1_000) == HLS_DIR

    def test_url_is_stable_within_a_bucket_and_lives_at_least_the_ttl(self) -> None:
        first = signer().sign(HLS_DIR, now=3_601)
        later = signer().sign(HLS_DIR, now=7_199)

        assert first == later
        assert signer().verify(later, now=7_199 + 7_200) == HLS_DIR

    def test_expired_token_is_rejected(self) -> None:
        token = signer().sign(HLS_DIR, now=0)

        with pytest.raises(HlsPlaylistNotFoundError):
            signer().verify(token, now=7_200 + 3_600 + 1)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
            lambda t: t.replace(".", ".9", 1),
            lambda t: "bWVkaWEvb3RoZXI" + t[t.index("."):],
            lambda _t: "garbage",
            lambda _t: "a.b.c",
        ],
    )
    def test_tampered_token_is_rejected(self, mutate) -> None:  # type: ignore[no-untyped-def]
        token = signer().sign(HLS_DIR, now=1_000)

        with pytest.raises(HlsPlaylistNotFoundError):
            signer().verify(mutate(token), now=1_000)

    def test_token_from_another_secret_is_rejected(self) -> None:
        token = signer(secret=b"x" * 32).sign(HLS_DIR, now=1_000)

        with pytest.raises(HlsPlaylistNotFoundError):
            signer().verify(token, now=1_000)


@pytest.mark.unit
@pytest.mark.chats
@pytest.mark.asyncio
class TestPlaylistRewrite:

    async def test_media_file_is_signed_once_per_playlist(self) -> None:
        storage = RecordingStorage()
        service = HlsPlaylistService(storage_service=storage, redis=None, signer=signer())  # type: ignore[arg-type]
        playlist = (
            "#EXTM3U\n"
            '#EXT-X-MAP:URI="v0.mp4",BYTERANGE="1372@0"\n'
            "#EXTINF:4.0,\n#EXT-X-BYTERANGE:227155@1372\nv0.mp4\n"
            "#EXTINF:4.0,\n#EXT-X-BYTERANGE:223676@228527\nv0.mp4\n"
            "#EXT-X-ENDLIST\n"
        )

        rewritten = await service._rewrite(HLS_DIR, playlist)

        signed = f"https://storage.test/{chat_config.ATTACHMENT_BUCKET}/{HLS_DIR}/v0.mp4?sig=1&expires={chat_config.HLS_SEGMENT_URL_TTL}"
        assert storage.presigned == [f"{HLS_DIR}/v0.mp4"]
        assert f'#EXT-X-MAP:URI="{signed}",BYTERANGE="1372@0"' in rewritten
        assert rewritten.count(f"\n{signed}\n") == 2
        assert "#EXT-X-BYTERANGE:223676@228527" in rewritten

    async def test_master_keeps_variant_playlists_relative(self) -> None:
        storage = RecordingStorage()
        service = HlsPlaylistService(storage_service=storage, redis=None, signer=signer())  # type: ignore[arg-type]
        master = master_playlist(plan_renditions(1280, 720), has_audio=True)

        rewritten = await service._rewrite(HLS_DIR, master)

        assert storage.presigned == []
        assert rewritten == master

    @pytest.mark.parametrize("uri", ["../../chats/secret.mp4", "https://evil.test/x.mp4", "a/b.mp4"])
    async def test_foreign_uri_in_a_playlist_is_refused(self, uri: str) -> None:
        service = HlsPlaylistService(storage_service=RecordingStorage(), redis=None, signer=signer())  # type: ignore[arg-type]

        with pytest.raises(HlsPlaylistNotFoundError):
            await service._rewrite(HLS_DIR, f"#EXTM3U\n#EXTINF:4.0,\n{uri}\n")

    @pytest.mark.parametrize("name", ["../master.m3u8", "v0.mp4", "index.m3u8", "v100.m3u8"])
    async def test_only_known_playlist_names_are_served(self, name: str) -> None:
        service = HlsPlaylistService(storage_service=RecordingStorage(), redis=None, signer=signer())  # type: ignore[arg-type]

        with pytest.raises(HlsPlaylistNotFoundError):
            await service.render(signer().sign(HLS_DIR), name)
