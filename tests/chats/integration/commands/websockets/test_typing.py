from datetime import datetime, timedelta
from uuid import uuid4

import orjson
import pytest
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.websockets.typing import TypingCommand, TypingCommandHandler
from app.chats.config import chat_config
from app.chats.models.blocks import ChatUserBlock
from app.chats.models.chat import Chat, ChatType
from app.chats.schemas.ws import TypingAction
from app.core.utils import now_utc
from app.core.websocket.dtos import DeliveryData, DeliveryDTO
from app.core.websocket.keys import WebsocketKeys
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.presence import PresenceService
from app.core.websocket.websocket import WSConnection
from tests.chats.integration.conftest import GATEWAY_ID
from tests.core.unit.test_ws_connection import make_connection


def sent_frames(conn: WSConnection) -> list[dict]:
    frames = []
    while not conn.send_queue.empty():
        frames.append(orjson.loads(conn.send_queue.get_nowait()))
    return frames


@pytest.fixture
async def handler(request_container: AsyncContainer) -> TypingCommandHandler:
    return await request_container.get(TypingCommandHandler)


@pytest.fixture
def create_chat(db_session: AsyncSession):
    async def _create(chat_type: ChatType, members: list[int]) -> Chat:
        chat = Chat.create(created_by=1, members_ids=members, chat_type=chat_type, name="typing")
        db_session.add(chat)
        await db_session.commit()
        return chat

    return _create


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestTypingCommand:

    async def test_typing_reaches_online_peer_but_not_the_typist(
        self,
        handler: TypingCommandHandler,
        direct_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(1)
        await go_online(2)
        conn = make_connection(user_id=1)

        await handler.handle(TypingCommand(conn=conn, chat_id=direct_chat.id))

        frames = await delivered_frames()
        assert len(frames) == 1
        frame = frames[0]
        assert frame["type"] == "typing_start"
        assert frame["channel"] == str(direct_chat.id)
        assert frame["delivery"] == {"require_subscription": False, "recipients": [2]}
        assert frame["payload"]["event_name"] == "typing_start"
        assert frame["payload"]["event"] == {
            "user_id": 1,
            "action": "typing",
            "expires_in": chat_config.TYPING_TTL_SECONDS,
        }
        assert frame["payload"]["message"] is None
        expires_at = datetime.fromisoformat(frame["expires_at"])
        assert expires_at - datetime.fromisoformat(frame["ts"]) == timedelta(
            seconds=chat_config.TYPING_TTL_SECONDS
        )
        assert sent_frames(conn) == []

    async def test_repeats_are_throttled_but_a_new_action_goes_through(
        self,
        handler: TypingCommandHandler,
        direct_chat: Chat,
        go_online,
        delivered_frames,
        count_sql,
    ) -> None:
        await go_online(2)
        conn = make_connection(user_id=1)

        await handler.handle(TypingCommand(conn=conn, chat_id=direct_chat.id))
        with count_sql() as statements:
            for _ in range(5):
                await handler.handle(TypingCommand(conn=conn, chat_id=direct_chat.id))

        assert statements == []
        assert len(await delivered_frames()) == 1

        await handler.handle(
            TypingCommand(conn=conn, chat_id=direct_chat.id, action=TypingAction.UPLOAD_PHOTO)
        )
        frames = await delivered_frames()
        assert [frame["payload"]["event"]["action"] for frame in frames] == ["typing", "upload_photo"]

    async def test_resend_after_the_interval_is_broadcast_again(
        self,
        handler: TypingCommandHandler,
        direct_chat: Chat,
        go_online,
        delivered_frames,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(chat_config, "TYPING_BROADCAST_INTERVAL_MS", 0)
        await go_online(2)
        conn = make_connection(user_id=1)

        for _ in range(3):
            await handler.handle(TypingCommand(conn=conn, chat_id=direct_chat.id))

        assert len(await delivered_frames()) == 3

    async def test_cancel_sends_stop_only_for_an_active_indicator(
        self,
        handler: TypingCommandHandler,
        direct_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)
        conn = make_connection(user_id=1)
        cancel = TypingCommand(conn=conn, chat_id=direct_chat.id, action=TypingAction.CANCEL)

        await handler.handle(cancel)
        assert await delivered_frames() == []

        await handler.handle(
            TypingCommand(conn=conn, chat_id=direct_chat.id, action=TypingAction.RECORD_VOICE)
        )
        await handler.handle(cancel)
        await handler.handle(cancel)

        frames = await delivered_frames()
        assert [frame["type"] for frame in frames] == ["typing_start", "typing_stop"]
        assert frames[1]["payload"]["event"] == {"user_id": 1}
        assert frames[1]["payload"]["event_name"] == "typing_stop"

    async def test_group_fanout_reaches_every_online_member(
        self,
        handler: TypingCommandHandler,
        create_chat,
        go_online,
        delivered_frames,
    ) -> None:
        chat = await create_chat(ChatType.GROUP, [2, 3, 4])
        for user_id in (2, 4):
            await go_online(user_id)
        conn = make_connection(user_id=3)

        await handler.handle(TypingCommand(conn=conn, chat_id=chat.id))

        (frame,) = await delivered_frames()
        assert frame["delivery"]["recipients"] == [2, 4]

    async def test_supergroup_reaches_only_active_subscribers(
        self,
        handler: TypingCommandHandler,
        create_chat,
        go_online,
        delivered_frames,
        redis_client: Redis,
    ) -> None:
        chat = await create_chat(ChatType.SUPERGROUP, [2, 3])
        await go_online(3)
        for user_id in (1, 2):
            connection_id = f"conn-{user_id}"
            await redis_client.sadd(
                WebsocketKeys.active_subscription_key(str(chat.id)),
                WebsocketKeys.active_subscription_route(user_id, GATEWAY_ID, connection_id),
            )
            await redis_client.set(WebsocketKeys.connection_key(connection_id), "{}")

        await handler.handle(TypingCommand(conn=make_connection(user_id=1), chat_id=chat.id))

        (frame,) = await delivered_frames()
        assert frame["delivery"] == {"require_subscription": True, "recipients": [2]}

    async def test_outsider_gets_one_error_and_no_further_queries(
        self,
        handler: TypingCommandHandler,
        direct_chat: Chat,
        go_online,
        delivered_frames,
        count_sql,
    ) -> None:
        await go_online(2)
        conn = make_connection(user_id=9)

        await handler.handle(TypingCommand(conn=conn, chat_id=direct_chat.id))
        with count_sql() as statements:
            await handler.handle(
                TypingCommand(conn=conn, chat_id=direct_chat.id, action=TypingAction.UPLOAD_FILE)
            )

        assert statements == []
        errors = sent_frames(conn)
        assert [(frame["type"], frame["code"]) for frame in errors] == [("ws.error", "NOT_FOUND_CHAT")]
        assert await delivered_frames() == []

    async def test_channel_subscriber_cannot_type(
        self,
        handler: TypingCommandHandler,
        create_chat,
        go_online,
        delivered_frames,
    ) -> None:
        chat = await create_chat(ChatType.CHANNEL, [2])
        await go_online(1)
        conn = make_connection(user_id=2)

        await handler.handle(TypingCommand(conn=conn, chat_id=chat.id))

        assert [frame["code"] for frame in sent_frames(conn)] == ["CHAT_ACCESS_DENIED"]
        assert await delivered_frames() == []

    async def test_blocked_direct_peer_does_not_see_typing(
        self,
        handler: TypingCommandHandler,
        direct_chat: Chat,
        db_session: AsyncSession,
        go_online,
        delivered_frames,
    ) -> None:
        db_session.add(ChatUserBlock(owner_id=2, target_id=1))
        await db_session.commit()
        await go_online(2)
        conn = make_connection(user_id=1)

        await handler.handle(TypingCommand(conn=conn, chat_id=direct_chat.id))

        assert [frame["code"] for frame in sent_frames(conn)] == ["USER_BLOCKED"]
        assert await delivered_frames() == []

    async def test_unknown_chat_is_reported_as_not_a_member(self, handler: TypingCommandHandler) -> None:
        conn = make_connection(user_id=1)

        await handler.handle(TypingCommand(conn=conn, chat_id=uuid4()))

        assert [frame["code"] for frame in sent_frames(conn)] == ["NOT_FOUND_CHAT"]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestGatewayDropsExpiredEntries:

    async def test_expired_entry_is_acked_but_not_sent(self, redis_client: Redis) -> None:
        manager = ConnectionManager(
            redis=redis_client,
            presence_service=PresenceService(redis=redis_client),
            gateway_id=GATEWAY_ID,
        )
        conn = make_connection(user_id=2)
        async with manager._lock:
            manager.connections_by_id[conn.connection_id] = conn
            manager.connections_by_user[conn.user_id].add(conn.connection_id)

        def entry(expires_at: datetime | None) -> dict[str, str]:
            return {
                "event": DeliveryDTO(
                    type="typing_start",
                    channel=str(uuid4()),
                    payload={"event": {"user_id": 1}},
                    delivery=DeliveryData(require_subscription=False, recipients=[2]),
                    ts=now_utc().isoformat(),
                    expires_at=expires_at.isoformat() if expires_at else None,
                ).model_dump_json()
            }

        assert await manager._process_gateway_stream_entry(
            "1-0", entry(now_utc() - timedelta(seconds=1))
        ) == "1-0"
        assert sent_frames(conn) == []

        await manager._process_gateway_stream_entry("2-0", entry(now_utc() + timedelta(seconds=5)))
        await manager._process_gateway_stream_entry("3-0", entry(None))
        assert [frame["type"] for frame in sent_frames(conn)] == ["typing_start", "typing_start"]
