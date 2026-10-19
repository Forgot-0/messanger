import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.models.chat_roles import ChatRoleId
from app.chats.models.message import Message
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.services.delivery_router import ChatDeliveryRouter
from app.chats.services.messages import MessageService
from app.chats.services.reaction_coalescer import ReactionCoalesceQueue
from app.core.consumers.event import DictEventDTO
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from app.core.websocket.dtos import DeliveryDTO
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.presence import PresenceService
from app.core.websocket.websocket import WSConnection
from app.notifications.consumers.chat_offline_delivery import OfflineEventDTO
from tests.chats.integration.conftest import GATEWAY_ID
from tests.core.unit.test_ws_connection import make_connection
from tests.mocks import FakeMessageBroker


@pytest.fixture
def broker() -> FakeMessageBroker:
    return FakeMessageBroker()


@pytest.fixture
def coalesce_queue(redis_client: Redis) -> ReactionCoalesceQueue:
    return ReactionCoalesceQueue(redis=redis_client)


@pytest.fixture
def delivery_router(
    redis_client: Redis,
    chat_repository: ChatRepository,
    message_repository: MessageRepository,
    message_service: MessageService,
    coalesce_queue: ReactionCoalesceQueue,
    broker: FakeMessageBroker,
) -> ChatDeliveryRouter:
    return ChatDeliveryRouter(
        redis=redis_client,
        chat_repository=chat_repository,
        message_repository=message_repository,
        message_service=message_service,
        coalesce_queue=coalesce_queue,
        broker=broker,
    )


def _message_sent_event(chat: Chat, message: Message, sender_id: int) -> DictEventDTO:
    return chat_event(
        "chats.message.sent",
        {
            "chat_id": str(chat.id),
            "message_id": str(message.id),
            "seq": message.seq,
            "sender_id": sender_id,
            "message_type": "text",
        },
    )


async def _mute_notifications(
    db_session: AsyncSession, chat: Chat, user_id: int, until: datetime
) -> None:
    await db_session.execute(
        update(ChatMember)
        .where(ChatMember.chat_id == chat.id, ChatMember.user_id == user_id)
        .values(notifications_muted_until=until)
    )
    await db_session.commit()


async def _set_member_role(
    db_session: AsyncSession, chat: Chat, user_id: int, role_id: int
) -> None:
    await db_session.execute(
        update(ChatMember)
        .where(ChatMember.chat_id == chat.id, ChatMember.user_id == user_id)
        .values(role_id=role_id)
    )
    await db_session.commit()


async def _override_permission(
    db_session: AsyncSession, chat: Chat, user_id: int, overrides: dict[str, bool]
) -> None:
    await db_session.execute(
        update(ChatMember)
        .where(ChatMember.chat_id == chat.id, ChatMember.user_id == user_id)
        .values(permissions_overrides=overrides)
    )
    await db_session.commit()


def chat_event(event_name: str, payload: dict) -> DictEventDTO:
    return DictEventDTO(
        event_name=event_name,
        event_id=uuid4(),
        payload=payload,
        created_at=now_utc(),
    )


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatDeliveryRouter:
    async def test_messages_read_delivers_reader_id_and_seq_delta(
        self,
        delivery_router: ChatDeliveryRouter,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)

        event = chat_event(
            "chats.message.readed",
            {"chat_id": str(group_chat.id), "seq": 17, "reader_id": 3},
        )
        await delivery_router.route_broker_message(event)

        frames = await delivered_frames()
        assert len(frames) == 1

        frame = frames[0]
        assert frame["type"] == "messages_read"
        assert frame["channel"] == str(group_chat.id)
        assert frame["delivery"]["recipients"] == [2]
        assert frame["payload"]["event_id"] == str(event.event_id)
        assert frame["payload"]["event_name"] == "chats.message.readed"
        assert frame["payload"]["event"] == {"seq": 17, "reader_id": 3}
        assert frame["payload"]["message"] is None

    async def test_new_message_carries_hydrated_message_and_delta(
        self,
        delivery_router: ChatDeliveryRouter,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        message: Message = await create_message(group_chat, user_jwt, "hello")
        await go_online(2)

        await delivery_router.route_broker_message(
            chat_event(
                "chats.message.sent",
                {
                    "chat_id": str(group_chat.id),
                    "message_id": str(message.id),
                    "seq": message.seq,
                    "sender_id": int(user_jwt.id),
                    "message_type": "text",
                },
            )
        )

        frames = await delivered_frames()
        assert len(frames) == 1

        payload = frames[0]["payload"]
        assert frames[0]["type"] == "new_message"
        assert payload["message"]["id"] == str(message.id)
        assert payload["message"]["content"] == "hello"
        assert payload["event"]["seq"] == message.seq
        assert payload["event"]["sender_id"] == int(user_jwt.id)

    async def test_offline_members_are_signalled_in_consumer_shape(
        self,
        delivery_router: ChatDeliveryRouter,
        broker: FakeMessageBroker,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        go_online,
    ) -> None:
        message: Message = await create_message(group_chat, user_jwt, "ping")
        await go_online(2)

        await delivery_router.route_broker_message(
            chat_event(
                "chats.message.sent",
                {
                    "chat_id": str(group_chat.id),
                    "message_id": str(message.id),
                    "seq": message.seq,
                    "sender_id": int(user_jwt.id),
                    "message_type": "text",
                },
            )
        )

        assert len(broker.sent_data) == 1
        _key, topic, data = broker.sent_data[0]
        assert topic == "chats.offline-delivery"

        signal = OfflineEventDTO.model_validate(data)
        assert signal.chat_id == group_chat.id
        assert signal.message_id == message.id
        # 2 онлайн, автор пуш себе не получает — остаётся только третий участник.
        assert signal.offline_user_ids == [3]

    async def test_muted_members_are_cut_from_the_offline_push_signal(
        self,
        delivery_router: ChatDeliveryRouter,
        broker: FakeMessageBroker,
        db_session: AsyncSession,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        go_online,
    ) -> None:
        chat: Chat = await create_group_chat(members=[2, 3, 4], name="Muted fanout")
        message: Message = await create_message(chat, user_jwt, "ping")
        await _mute_notifications(db_session, chat, user_id=3, until=now_utc() + timedelta(hours=1))
        # Истёкший мьют не считается — участник обязан остаться в сигнале.
        await _mute_notifications(db_session, chat, user_id=4, until=now_utc() - timedelta(hours=1))
        await go_online(2)

        await delivery_router.route_broker_message(
            _message_sent_event(chat, message, sender_id=int(user_jwt.id))
        )

        assert len(broker.sent_data) == 1
        _key, topic, data = broker.sent_data[0]
        assert topic == "chats.offline-delivery"
        # Оффлайн были 3 и 4, но у 3 мьют — пуш уходит только четвёртому.
        assert OfflineEventDTO.model_validate(data).offline_user_ids == [4]

    async def test_mute_does_not_touch_ws_delivery(
        self,
        delivery_router: ChatDeliveryRouter,
        broker: FakeMessageBroker,
        db_session: AsyncSession,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        chat: Chat = await create_group_chat(members=[2], name="Muted realtime")
        message: Message = await create_message(chat, user_jwt, "ping")
        await _mute_notifications(db_session, chat, user_id=2, until=now_utc() + timedelta(hours=1))
        await go_online(2)

        await delivery_router.route_broker_message(
            _message_sent_event(chat, message, sender_id=int(user_jwt.id))
        )

        # Мьют — это про уведомления, realtime замьютивший получает как обычно.
        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "new_message"
        assert frames[0]["delivery"]["recipients"] == [2]
        # Все оффлайн-получатели отфильтрованы — сигнала на push нет вовсе.
        assert broker.sent_data == []

    async def test_kicked_member_is_notified_after_leaving_the_chat(
        self,
        delivery_router: ChatDeliveryRouter,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        kicked_user_id = 90_001
        await go_online(kicked_user_id)

        await delivery_router.route_broker_message(
            chat_event(
                "chats.member.kicked",
                {
                    "chat_id": str(group_chat.id),
                    "requester_id": 1,
                    "target_user_id": kicked_user_id,
                },
            )
        )

        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "member_kick"
        assert frames[0]["delivery"]["recipients"] == [kicked_user_id]
        assert frames[0]["payload"]["event"]["target_user_id"] == kicked_user_id
        assert frames[0]["payload"]["event"]["requester_id"] == 1

    async def test_deleted_chat_event_reaches_members(
        self,
        delivery_router: ChatDeliveryRouter,
        db_session: AsyncSession,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)
        group_chat.delete(deleted_by=1)
        group_chat.pull_events()
        await db_session.commit()

        await delivery_router.route_broker_message(
            chat_event(
                "chats.chat.deleted",
                {"chat_id": str(group_chat.id), "deleted_by": 1},
            )
        )

        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "chat_deleted"
        assert frames[0]["payload"]["event"] == {"deleted_by": 1}

    async def test_unknown_event_name_is_skipped(
        self,
        delivery_router: ChatDeliveryRouter,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)

        await delivery_router.route_broker_message(
            chat_event("chats.chat.archived", {"chat_id": str(group_chat.id)})
        )

        assert await delivered_frames() == []

    async def test_reaction_event_is_coalesced_then_delivered_with_groups(
        self,
        delivery_router: ChatDeliveryRouter,
        coalesce_queue: ReactionCoalesceQueue,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        message: Message = await create_message(group_chat, user_jwt, "react to me")
        await go_online(2)

        payload = {
            "chat_id": str(group_chat.id),
            "message_id": str(message.id),
            "actor_id": 3,
            "action": "add",
            "groups": [{"emoji": "🔥", "count": 1}],
            "recent_by_emoji": {"🔥": [3]},
        }
        await delivery_router.route_broker_message(
            chat_event("chats.message.reaction_updated", payload)
        )

        assert await delivered_frames() == []

        for snapshot in await _claim_all(coalesce_queue):
            await delivery_router.route_reaction_snapshot(snapshot)

        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "reaction_update"

        ws_payload = frames[0]["payload"]
        assert ws_payload["reaction"]["groups"] == [
            {"emoji": "🔥", "count": 1, "reacted_by_me": False, "recent_user_ids": [3]}
        ]
        # Снимок групп едет в reaction, в дельте — только кто и что сделал.
        assert ws_payload["event"] == {
            "message_id": str(message.id),
            "actor_id": 3,
            "action": "add",
        }


async def _claim_all(queue: ReactionCoalesceQueue) -> list[DictEventDTO]:
    await asyncio.sleep(chat_config.REACTIONS_COALESCE_WINDOW_MS / 1000)
    return await queue.claim_due()


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestGatewayDelivery:
    async def test_event_reaches_connected_client_frame(
        self,
        delivery_router: ChatDeliveryRouter,
        redis_client: Redis,
        group_chat: Chat,
    ) -> None:
        manager = ConnectionManager(
            redis=redis_client,
            presence_service=PresenceService(redis=redis_client),
            gateway_id=GATEWAY_ID,
        )
        conn = make_connection(user_id=2)
        await manager.register(conn)

        try:
            await delivery_router.route_broker_message(
                chat_event(
                    "chats.message.readed",
                    {"chat_id": str(group_chat.id), "seq": 42, "reader_id": 3},
                )
            )

            for entry in await _read_gateway_stream(redis_client, manager):
                await manager.send_to_users_local(DeliveryDTO.model_validate_json(entry))

            frame = json.loads(await _wait_sent_frame(conn))
        finally:
            await manager.unregister(conn)

        assert frame["type"] == "messages_read"
        assert frame["channel"] == str(group_chat.id)
        assert frame["payload"]["event"] == {"seq": 42, "reader_id": 3}


async def _wait_sent_frame(conn: WSConnection, timeout: float = 2.0) -> str:
    """Кадр уходит в сокет писателем соединения — ждём его, а не читаем очередь."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if conn.websocket.send_text.await_args is not None:
            return conn.websocket.send_text.await_args.args[0]
        await asyncio.sleep(0.01)

    raise AssertionError("websocket frame was not sent")


async def _read_gateway_stream(redis: Redis, manager: ConnectionManager) -> list[str]:
    await redis.xgroup_create(
        name=manager.stream_key, groupname=manager.stream_group, id="0-0", mkstream=True
    )
    messages = await redis.xreadgroup(
        groupname=manager.stream_group,
        consumername=manager.stream_consumer,
        streams={manager.stream_key: ">"},
        count=10,
    )
    return [
        fields["event"]
        for _stream, stream_messages in messages
        for _message_id, fields in stream_messages
    ]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestDeliveryRouterPinsAndSilentMessages:
    async def test_message_without_notify_skips_the_offline_push(
        self,
        delivery_router: ChatDeliveryRouter,
        broker: FakeMessageBroker,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        message: Message = await create_message(group_chat, user_jwt, "part of a batch")
        await go_online(2)
        event = _message_sent_event(group_chat, message, sender_id=int(user_jwt.id))
        event.payload["notify"] = False

        await delivery_router.route_broker_message(event)

        assert broker.sent_data == []
        frames = await delivered_frames()
        assert [frame["type"] for frame in frames] == ["new_message"]
        assert frames[0]["payload"]["event"]["notify"] is False

    async def test_pin_events_reach_members_as_deltas(
        self,
        delivery_router: ChatDeliveryRouter,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)
        message_id = str(uuid4())

        await delivery_router.route_broker_message(chat_event(
            "chats.message.pinned",
            {
                "chat_id": str(group_chat.id),
                "message_id": message_id,
                "seq": 7,
                "pinned_by": 1,
                "pinned_at": now_utc().isoformat(),
            },
        ))
        await delivery_router.route_broker_message(chat_event(
            "chats.message.unpinned",
            {
                "chat_id": str(group_chat.id),
                "message_ids": [message_id],
                "unpinned_by": 1,
                "all": False,
            },
        ))

        pinned, unpinned = await delivered_frames()
        assert pinned["type"] == "message_pinned"
        assert pinned["payload"]["event"]["message_id"] == message_id
        assert pinned["payload"]["event"]["seq"] == 7
        assert pinned["payload"]["message"] is None
        assert unpinned["type"] == "message_unpinned"
        assert unpinned["payload"]["event"] == {
            "message_ids": [message_id],
            "unpinned_by": 1,
            "all": False,
        }

    async def test_join_request_reaches_only_those_who_can_decide(
        self,
        delivery_router: ChatDeliveryRouter,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        # 1 — владелец, 2 — админ (может решать), 3 — editor: прав на заявки у него нет.
        await _set_member_role(db_session, group_chat, 2, ChatRoleId.ADMIN)
        await _set_member_role(db_session, group_chat, 3, ChatRoleId.EDITOR)
        await go_online(int(user_jwt.id))
        await go_online(2)
        await go_online(3)

        await delivery_router.route_broker_message(chat_event(
            "chats.join_request.created",
            {
                "chat_id": str(group_chat.id),
                "user_id": 42,
                "invite_link_id": None,
                "requested_at": now_utc().isoformat(),
            },
        ))

        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "join_request_created"
        assert frames[0]["delivery"]["recipients"] == [int(user_jwt.id), 2]
        assert frames[0]["delivery"]["require_subscription"] is False
        assert frames[0]["payload"]["event"]["user_id"] == 42

    async def test_personal_deny_cuts_moderator_from_join_request_fanout(
        self,
        delivery_router: ChatDeliveryRouter,
        db_session: AsyncSession,
        group_chat: Chat,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        await _set_member_role(db_session, group_chat, 2, ChatRoleId.ADMIN)
        await _override_permission(db_session, group_chat, 2, {"member:invite": False})
        await go_online(int(user_jwt.id))
        await go_online(2)

        await delivery_router.route_broker_message(chat_event(
            "chats.join_request.created",
            {
                "chat_id": str(group_chat.id),
                "user_id": 42,
                "invite_link_id": None,
                "requested_at": now_utc().isoformat(),
            },
        ))

        frames = await delivered_frames()
        assert frames[0]["delivery"]["recipients"] == [int(user_jwt.id)]

    async def test_decision_also_reaches_the_applicant(
        self,
        delivery_router: ChatDeliveryRouter,
        group_chat: Chat,
        user_jwt: UserJWTData,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(int(user_jwt.id))
        await go_online(42)

        await delivery_router.route_broker_message(chat_event(
            "chats.join_request.declined",
            {
                "chat_id": str(group_chat.id),
                "user_ids": [42],
                "resolved_by": int(user_jwt.id),
                "count": 1,
                "all": False,
            },
        ))

        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "join_request_declined"
        assert frames[0]["delivery"]["recipients"] == [int(user_jwt.id), 42]
