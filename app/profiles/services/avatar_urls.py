import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from redis.asyncio import Redis

from app.core.services.storage.service import StorageService
from app.profiles.config import profile_config
from app.profiles.keys import ProfileAvatarKeys


class AvatarMapHolder(Protocol):
    avatars: dict[Any, dict[Any, str]]


@dataclass
class ProfileAvatarUrlService:
    redis: Redis
    storage_service: StorageService

    async def attach(self, holders: Iterable[AvatarMapHolder | None]) -> None:
        targets = [holder for holder in holders if holder is not None and holder.avatars]
        if not targets:
            return

        urls = await self.presigned_urls(
            value
            for holder in targets
            for variants in holder.avatars.values()
            for value in variants.values()
        )

        for holder in targets:
            holder.avatars = {
                size: {
                    fmt: urls.get(self._to_key(value), value)
                    for fmt, value in variants.items()
                }
                for size, variants in holder.avatars.items()
            }

    async def presigned_urls(self, values: Iterable[str]) -> dict[str, str]:
        keys = list(dict.fromkeys(
            key
            for key in (self._to_key(value) for value in values if value)
            if not key.startswith("http")
        ))
        if not keys:
            return {}

        urls: dict[str, str] = {}
        cached = await self.redis.mget([ProfileAvatarKeys.download_url(key) for key in keys])

        missing: list[str] = []
        for key, url in zip(keys, cached, strict=True):
            if url is None:
                missing.append(key)
            else:
                urls[key] = str(url)

        if not missing:
            return urls

        signed = await asyncio.gather(*(
            self.storage_service.generate_presigned_url(
                bucket_name=profile_config.AVATAR_BUCKET,
                file_key=key,
                expires=profile_config.AVATAR_URL_TTL,
            )
            for key in missing
        ))

        async with self.redis.pipeline(transaction=False) as pipe:
            for key, url in zip(missing, signed, strict=True):
                pipe.set(
                    ProfileAvatarKeys.download_url(key),
                    url,
                    ex=profile_config.AVATAR_URL_TTL - profile_config.AVATAR_URL_CACHE_SKEW,
                )
            await pipe.execute()

        urls.update(zip(missing, signed, strict=True))
        return urls

    @staticmethod
    def _to_key(value: str) -> str:
        if not value.startswith("http"):
            return value

        _, marker, tail = value.partition(f"/{profile_config.AVATAR_BUCKET}/")
        return tail if marker and tail else value
