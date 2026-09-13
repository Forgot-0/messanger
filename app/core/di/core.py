from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from app.core.configs.app import app_config
from app.core.services.idempotency import IdempotencyStore
from app.core.services.media.probe.ffprobe import FfprobeMediaProbeService
from app.core.services.media.service import MediaProbeService
from app.core.services.storage.aioboto.client import s3_client
from app.core.services.storage.aioboto.service import AioBotoStorageService
from app.core.services.storage.policy import Policy
from app.core.services.storage.service import StorageService


class CoreProvider(Provider):

    @provide(scope=Scope.APP)
    def idempotency_store(self, redis: Redis) -> IdempotencyStore:
        return IdempotencyStore(redis=redis)

    @provide(scope=Scope.APP)
    def media_probe(self) -> MediaProbeService:
        return FfprobeMediaProbeService()

    @provide(scope=Scope.APP)
    def bucket_policy(self) -> dict[str, Policy]:
        return {
            "base": Policy.NONE
        }

    @provide(scope=Scope.APP)
    async def storage_service(self, bucket_policy: dict[str, Policy]) -> AsyncIterator[StorageService]:
        async with AsyncExitStack() as stack:
            internal = await stack.enter_async_context(
                s3_client(
                    endpoint_url=app_config.storage_endpoint_url,
                    access_key=app_config.STORAGE_ACCESS_KEY,
                    secret_key=app_config.STORAGE_SECRET_KEY,
                    region=app_config.STORAGE_REGION,
                )
            )
            public = await stack.enter_async_context(
                s3_client(
                    endpoint_url=app_config.storage_public_endpoint_url,
                    access_key=app_config.STORAGE_ACCESS_KEY,
                    secret_key=app_config.STORAGE_SECRET_KEY,
                    region=app_config.STORAGE_REGION,
                )
            )

            service = AioBotoStorageService(
                client=internal,
                public_client=public,
                bucket_policy=bucket_policy,
                public_base_url=app_config.storage_public_endpoint_url,
                sse_enabled=app_config.STORAGE_SSE,
            )
            await service.ensure_buckets()

            yield service
