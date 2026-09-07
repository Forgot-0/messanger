from collections.abc import Iterable
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.configs.app import app_config
from app.core.utils import now_utc
from app.core.websocket.keys import WebsocketKeys


@dataclass
class PresenceService:
    redis: Redis

    def _is_fresh_score(self, score: float | None, now_ts: float) -> bool:
        if score is None:
            return False
        return (now_ts - score) <= app_config.WS_PRESENCE_TTL

    async def set_online(self, user_id: int) -> None:
        ts = now_utc().timestamp()
        await self.redis.zadd(WebsocketKeys.presence_last_seen_zset(), {str(user_id): ts})

    async def refresh(self, user_ids: Iterable[int]) -> None:
        mapping = {str(user_id): now_utc().timestamp() for user_id in user_ids}

        if not mapping:
            return

        await self.redis.zadd(WebsocketKeys.presence_last_seen_zset(), mapping)

    async def set_offline(self, user_id: int) -> None:
        await self.redis.zrem(WebsocketKeys.presence_last_seen_zset(), str(user_id))

    async def cleanup_stale(self) -> int:
        threshold = now_utc().timestamp() - app_config.WS_PRESENCE_TTL
        removed = await self.redis.zremrangebyscore(
            WebsocketKeys.presence_last_seen_zset(), min=0, max=threshold
        )
        return int(removed or 0)

    async def get_online_status(self, user_ids: list[int]) -> dict[int, bool]:
        if not user_ids:
            return {}

        now_ts = now_utc().timestamp()
        members = [str(uid) for uid in user_ids]
        scores = await self.redis.zmscore(WebsocketKeys.presence_last_seen_zset(), members)

        return {
            uid: self._is_fresh_score(score, now_ts)
            for uid, score in zip(user_ids, scores, strict=False)
        }

