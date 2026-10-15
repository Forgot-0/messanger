import asyncio
import base64
import binascii
import hashlib
import hmac
import math
import re
import time
from dataclasses import dataclass
from typing import Self

from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.exceptions import HlsPlaylistNotFoundError
from app.chats.keys import AttachmentKeys
from app.core.configs.app import app_config
from app.core.services.media.dtos import HlsRendition
from app.core.services.storage.exceptions import ObjectNotFoundError
from app.core.services.storage.service import StorageService

MASTER_PLAYLIST = "master.m3u8"
PLAYLIST_NAME = re.compile(r"^(?:master|v\d{1,2})\.m3u8$")
MEDIA_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}\.[a-z0-9]{1,8}$")
URI_ATTRIBUTE = re.compile(r'URI="([^"]*)"')

SIGNATURE_BYTES = 16
SIGNING_CONTEXT = b"chats.hls.v1"


def hls_eligible(width: int | None, height: int | None, duration_seconds: int | None) -> bool:
    if not chat_config.VIDEO_HLS_RENDITIONS:
        return False
    if not width or not height or not duration_seconds:
        return False
    return (
        max(width, height) <= chat_config.VIDEO_TRANSCODE_MAX_SOURCE_SIDE
        and duration_seconds <= chat_config.VIDEO_TRANSCODE_MAX_DURATION_SECONDS
    )


def plan_renditions(width: int, height: int) -> tuple[HlsRendition, ...]:
    short_side = min(width, height)
    ladder = sorted(chat_config.VIDEO_HLS_RENDITIONS.items())
    chosen = [(side, kbps) for side, kbps in ladder if side <= short_side] or [(short_side, ladder[0][1])]

    renditions: list[HlsRendition] = []
    for index, (side, kbps) in enumerate(chosen):
        scale = side / short_side
        renditions.append(
            HlsRendition(
                name=f"v{index}",
                width=_even(width * scale),
                height=_even(height * scale),
                video_kbps=kbps,
                audio_kbps=chat_config.VIDEO_HLS_AUDIO_KBPS,
            )
        )
    return tuple(renditions)


def master_playlist(renditions: tuple[HlsRendition, ...], *, has_audio: bool) -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for rendition in sorted(renditions, key=lambda item: item.bandwidth):
        bandwidth = rendition.bandwidth if has_audio else rendition.video_kbps * 1000
        lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={rendition.width}x{rendition.height}"
        )
        lines.append(f"{rendition.name}.m3u8")
    return "\n".join(lines) + "\n"


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


@dataclass(frozen=True)
class HlsUrlSigner:
    secret: bytes
    base_url: str
    ttl: int
    ttl_bucket: int

    @classmethod
    def from_config(cls) -> Self:
        return cls(
            secret=hmac.new(app_config.SECRET_KEY.encode(), SIGNING_CONTEXT, hashlib.sha256).digest(),
            base_url=chat_config.HLS_PUBLIC_BASE_URL.rstrip("/"),
            ttl=chat_config.HLS_URL_TTL,
            ttl_bucket=max(1, chat_config.HLS_URL_TTL_BUCKET),
        )

    def url(self, hls_key: str, now: float | None = None) -> str:
        prefix, _, name = hls_key.rpartition("/")
        token = self.sign(prefix, now)
        return f"{self.base_url}{app_config.API_V1_STR}/chats/media/hls/{token}/{name}"

    def sign(self, prefix: str, now: float | None = None) -> str:
        issued = time.time() if now is None else now
        expires = math.ceil((issued + self.ttl) / self.ttl_bucket) * self.ttl_bucket
        body = f"{_b64encode(prefix.encode())}.{expires}"
        return f"{body}.{self._signature(body)}"

    def verify(self, token: str, now: float | None = None) -> str:
        body, _, signature = token.rpartition(".")
        encoded_prefix, _, raw_expires = body.partition(".")
        if not signature or not encoded_prefix or not raw_expires.isdigit():
            raise HlsPlaylistNotFoundError

        if not hmac.compare_digest(signature, self._signature(body)):
            raise HlsPlaylistNotFoundError

        if int(raw_expires) < (time.time() if now is None else now):
            raise HlsPlaylistNotFoundError

        try:
            return _b64decode(encoded_prefix).decode()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise HlsPlaylistNotFoundError from exc

    def _signature(self, body: str) -> str:
        digest = hmac.new(self.secret, body.encode(), hashlib.sha256).digest()
        return _b64encode(digest[:SIGNATURE_BYTES])


@dataclass
class HlsPlaylistService:
    storage_service: StorageService
    redis: Redis
    signer: HlsUrlSigner

    async def render(self, token: str, name: str) -> str:
        if not PLAYLIST_NAME.match(name):
            raise HlsPlaylistNotFoundError

        prefix = self.signer.verify(token)
        playlist = await self._load(f"{prefix}/{name}")
        return await self._rewrite(prefix, playlist)

    async def _load(self, object_key: str) -> str:
        cache_key = AttachmentKeys.hls_playlist(object_key)
        cached = await self.redis.get(cache_key)
        if cached is not None:
            return str(cached)

        try:
            raw = await self.storage_service.download_bytes(
                chat_config.ATTACHMENT_BUCKET,
                object_key,
                max_bytes=chat_config.HLS_PLAYLIST_MAX_BYTES,
            )
        except ObjectNotFoundError as exc:
            raise HlsPlaylistNotFoundError from exc

        playlist = raw.decode("utf-8")
        await self.redis.set(cache_key, playlist, ex=chat_config.HLS_PLAYLIST_CACHE_TTL)
        return playlist

    async def _rewrite(self, prefix: str, playlist: str) -> str:
        lines = [line for line in playlist.splitlines() if line.strip()]

        media_names: set[str] = set()
        for line in lines:
            for uri in self._uris(line):
                if not uri.endswith(".m3u8"):
                    media_names.add(uri)

        for uri in {uri for line in lines for uri in self._uris(line)}:
            if not MEDIA_NAME.match(uri):
                raise HlsPlaylistNotFoundError

        ordered = sorted(media_names)
        signed = await asyncio.gather(*(
            self.storage_service.generate_presigned_url(
                bucket_name=chat_config.ATTACHMENT_BUCKET,
                file_key=f"{prefix}/{media_name}",
                expires=chat_config.HLS_SEGMENT_URL_TTL,
            )
            for media_name in ordered
        ))
        urls = dict(zip(ordered, signed, strict=True))

        rewritten: list[str] = []
        for line in lines:
            if line.startswith("#"):
                rewritten.append(
                    URI_ATTRIBUTE.sub(lambda match: f'URI="{urls.get(match.group(1), match.group(1))}"', line)
                )
            else:
                rewritten.append(urls.get(line.strip(), line.strip()))
        return "\n".join(rewritten) + "\n"

    @staticmethod
    def _uris(line: str) -> list[str]:
        if line.startswith("#"):
            return URI_ATTRIBUTE.findall(line)
        return [line.strip()]
