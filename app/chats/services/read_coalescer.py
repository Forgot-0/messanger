from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import orjson
from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.keys import ReadReceiptKeys
from app.core.utils import now_ms

_ENQUEUE_LUA = """
local pending, due = KEYS[1], KEYS[2]
local field, seq, payload, deadline = ARGV[1], tonumber(ARGV[2]), ARGV[3], tonumber(ARGV[4])

local current = redis.call('HGET', pending, field)
if current and tonumber(cjson.decode(current)['seq']) >= seq then
    return 0
end

redis.call('HSET', pending, field, payload)
redis.call('ZADD', due, 'NX', deadline, field)
return 1
"""

_CLAIM_DUE_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, tonumber(ARGV[2]))
local out = {}
for _, field in ipairs(due) do
    local payload = redis.call('HGET', KEYS[2], field)
    redis.call('ZREM', KEYS[1], field)
    redis.call('HDEL', KEYS[2], field)
    if payload then
        out[#out + 1] = field
        out[#out + 1] = payload
    end
end
return out
"""


@dataclass(frozen=True, slots=True)
class PendingReadCursor:
    chat_id: UUID
    user_id: int
    message_seq: int
    support_read_event: bool
    read_at: datetime


@dataclass
class ReadReceiptCoalesceQueue:
    redis: Redis

    async def enqueue(
        self,
        chat_id: UUID,
        user_id: int,
        message_seq: int,
        support_read_event: bool,
    ) -> bool:
        field = ReadReceiptKeys.coalesce_field(str(chat_id), user_id)
        ms = now_ms()
        payload = orjson.dumps({
            "seq": message_seq,
            "read_event": support_read_event,
            "at": ms,
        }).decode()

        accepted = await self.redis.eval(
            _ENQUEUE_LUA,
            2,
            ReadReceiptKeys.coalesce_pending(),
            ReadReceiptKeys.coalesce_due(),
            field,
            str(message_seq),
            payload,
            str(ms + chat_config.READ_RECEIPTS_COALESCE_WINDOW_MS),
        )
        return bool(accepted)

    async def claim_due(self) -> list[PendingReadCursor]:
        raw = await self.redis.eval(
            _CLAIM_DUE_LUA,
            2,
            ReadReceiptKeys.coalesce_due(),
            ReadReceiptKeys.coalesce_pending(),
            str(now_ms()),
            str(chat_config.READ_RECEIPTS_COALESCE_MAX_KEYS_PER_TICK),
        )

        cursors: list[PendingReadCursor] = []
        for field, payload in zip(raw[0::2], raw[1::2], strict=False):
            parsed = ReadReceiptKeys.parse_coalesce_field(field)
            if parsed is None:
                continue

            chat_id_raw, user_id = parsed
            cursor = self._parse(UUID(chat_id_raw), user_id, payload)
            if cursor is not None:
                cursors.append(cursor)

        return cursors

    async def peek_many(
        self, user_id: int, chat_ids: Sequence[UUID]
    ) -> dict[UUID, PendingReadCursor]:
        if not chat_ids:
            return {}

        fields = [
            ReadReceiptKeys.coalesce_field(str(chat_id), user_id)
            for chat_id in chat_ids
        ]
        payloads = await self.redis.hmget(ReadReceiptKeys.coalesce_pending(), fields)

        pending: dict[UUID, PendingReadCursor] = {}
        for chat_id, payload in zip(chat_ids, payloads, strict=False):
            if payload is None:
                continue
            cursor = self._parse(chat_id, user_id, payload)
            if cursor is not None:
                pending[chat_id] = cursor

        return pending

    @staticmethod
    def _parse(
        chat_id: UUID, user_id: int, payload: bytes | str
    ) -> PendingReadCursor | None:
        try:
            data = orjson.loads(payload)
            return PendingReadCursor(
                chat_id=chat_id,
                user_id=user_id,
                message_seq=int(data["seq"]),
                support_read_event=bool(data["read_event"]),
                read_at=datetime.fromtimestamp(int(data["at"]) / 1000, tz=UTC),
            )
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    async def requeue(self, cursors: list[PendingReadCursor]) -> None:
        for cursor in cursors:
            await self.enqueue(
                chat_id=cursor.chat_id,
                user_id=cursor.user_id,
                message_seq=cursor.message_seq,
                support_read_event=cursor.support_read_event,
            )
