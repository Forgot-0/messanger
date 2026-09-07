import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.keys import ReactionKeys
from app.core.consumers.event import DictEventDTO

_CLAIM_DUE_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, tonumber(ARGV[2]))
local out = {}
for _, field in ipairs(due) do
    local snapshot = redis.call('HGET', KEYS[2], field)
    redis.call('ZREM', KEYS[1], field)
    redis.call('HDEL', KEYS[2], field)
    if snapshot then
        out[#out + 1] = snapshot
    end
end
return out
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ReactionCoalesceQueue:
    redis: Redis

    async def enqueue(self, event: DictEventDTO) -> None:
        field = f"{event.payload['chat_id']}:{event.payload['message_id']}"
        deadline = _now_ms() + chat_config.REACTIONS_COALESCE_WINDOW_MS

        pipe = self.redis.pipeline(transaction=True)
        pipe.hset(ReactionKeys.reaction_coalesce_pending(), field, event.model_dump_json())
        pipe.zadd(ReactionKeys.reaction_coalesce_due(), {field: deadline}, nx=True)
        await pipe.execute()

    async def claim_due(self) -> list[DictEventDTO]:
        raw = await self.redis.eval(
            _CLAIM_DUE_LUA,
            2,
            ReactionKeys.reaction_coalesce_due(),
            ReactionKeys.reaction_coalesce_pending(),
            str(_now_ms()),
            str(chat_config.REACTIONS_COALESCE_MAX_KEYS_PER_TICK),
        )
        return [DictEventDTO.model_validate_json(item) for item in raw or []]
