from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.exceptions import IdempotencyConflictError

_RESULT_KEY_TEMPLATE = "idempotency:{scope}:{owner}:{key}"
_LOCK_KEY_TEMPLATE = "idempotency:{scope}:{owner}:{key}:lock"


@dataclass(slots=True)
class IdempotencyStore:
    redis: Redis
    result_ttl: int = 86_400
    lock_ttl: int = 30

    async def run[ResultT: BaseModel](
        self,
        *,
        scope: str,
        key: str | None,
        owner: Sequence[object],
        model: type[ResultT],
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        if not key:
            return await operation()

        keys = {"scope": scope, "owner": ":".join(str(part) for part in owner), "key": key}
        result_key = _RESULT_KEY_TEMPLATE.format(**keys)

        cached = await self.redis.get(result_key)
        if cached is not None:
            return model.model_validate_json(cached)

        lock_key = _LOCK_KEY_TEMPLATE.format(**keys)
        if not await self.redis.set(lock_key, "1", ex=self.lock_ttl, nx=True):
            raise IdempotencyConflictError(key=key)

        try:
            result = await operation()
            await self.redis.set(result_key, result.model_dump_json(), ex=self.result_ttl)
        finally:
            await self.redis.delete(lock_key)

        return result
