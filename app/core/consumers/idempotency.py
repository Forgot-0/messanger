from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis

_PROCESSED_KEY_TEMPLATE = "consumers:processed:{group}:{event_id}"


@dataclass(slots=True)
class EventIdempotencyGuard:
    redis: Redis
    ttl_seconds: int = 7 * 24 * 3600

    async def try_acquire(self, group: str, event_id: UUID) -> bool:
        key = _PROCESSED_KEY_TEMPLATE.format(group=group, event_id=event_id)
        acquired = await self.redis.set(key, "1", ex=self.ttl_seconds, nx=True)
        return bool(acquired)

    async def release(self, group: str, event_id: UUID) -> None:
        key = _PROCESSED_KEY_TEMPLATE.format(group=group, event_id=event_id)
        await self.redis.delete(key)
