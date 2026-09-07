import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.dtos.delivery import (
    CHAT_DELETED_EVENT_NAME,
    CHAT_EVENT_TO_WS_TYPE,
    MESSAGE_HYDRATED_EVENTS,
    REACTION_EVENT_NAME,
    MessagePayloadWS,
    WsEvent,
    build_reaction_ws_dto,
    chunks,
)
from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.reactions import ReactionUpdateWSDTO
from app.chats.metrics import (
    DELIVERY_ROUTER_OFFLINE_SIGNALS,
    DELIVERY_ROUTER_STREAM_ENTRIES,
)
from app.chats.models.chat import ChatFanoutStrategy
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.schemas.ws import WSEventType
from app.chats.services.messages import MessageService
from app.chats.services.reaction_coalescer import ReactionCoalesceQueue
from app.core.configs.app import app_config
from app.core.consumers.event import DictEventDTO
from app.core.message_brokers.base import BaseMessageBroker
from app.core.websocket.dtos import DeliveryData, DeliveryDTO
from app.core.websocket.keys import WebsocketKeys

RouteMap = dict[str, set[int]]
ActiveSubscriptionRoute = tuple[int, str, str, str]

OFFLINE_SIGNAL_EVENT_NAMES: frozenset[str] = frozenset({"chats.message.sent"})

MEMBER_REMOVED_EVENT_FIELDS: dict[str, str] = {
    "chats.member.kicked": "target_user_id",
    "chats.member.banned": "target_user_id",
    "chats.member.left": "user_id",
}


@dataclass
class ChatDeliveryRouter:
    redis: Redis
    chat_repository: ChatRepository
    message_repository: MessageRepository
    message_service: MessageService
    coalesce_queue: ReactionCoalesceQueue
    broker: BaseMessageBroker

    async def route_broker_message(self, event: DictEventDTO) -> None:
        ws_type = CHAT_EVENT_TO_WS_TYPE.get(event.event_name)
        if ws_type is None:
            return

        if event.event_name == REACTION_EVENT_NAME:
            await self.coalesce_queue.enqueue(event)
            return

        chat = await self.chat_repository.get_by_id(
            UUID(event.payload["chat_id"]),
            include_deleted=event.event_name == CHAT_DELETED_EVENT_NAME,
        )
        if chat is None:
            return

        ws_event = WsEvent.build(
            event, ws_type=ws_type, fanout_strategy=chat.fanout_strategy
        )

        message_dto: MessageDTO | None = None
        if event.event_name in MESSAGE_HYDRATED_EVENTS:
            message = await self.message_repository.get_by_id(
                UUID(event.payload["message_id"]), with_attachment=True
            )
            if message is None:
                return

            message_dto = await self.message_service.attach_download_urls(
                MessageDTO.model_validate(message)
            )

        await self._dispatch(ws_event, message=message_dto)

    async def route_reaction_snapshot(self, event: DictEventDTO) -> None:
        chat = await self.chat_repository.get_by_id(UUID(event.payload["chat_id"]))
        if chat is None:
            return

        ws_event = WsEvent.build(
            event,
            ws_type=WSEventType.REACTION_UPDATED.value,
            fanout_strategy=chat.fanout_strategy,
        )

        await self._dispatch(ws_event, reaction=build_reaction_ws_dto(event))

    async def _dispatch(
        self,
        ws_event: WsEvent,
        *,
        message: MessageDTO | None = None,
        reaction: ReactionUpdateWSDTO | None = None,
    ) -> None:
        payload = MessagePayloadWS(
            event_id=ws_event.event_id,
            event_name=ws_event.event_name,
            event=ws_event.delta,
            message=message,
            reaction=reaction,
        ).model_dump(mode="json")
        await self._route_to_removed_member(ws_event=ws_event, payload=payload)


        if ws_event.fanout_strategy == ChatFanoutStrategy.FANOUT_ON_WRITE:
            return await self._route_fanout_on_write(ws_event=ws_event, payload=payload)

        return await self._route_to_active_subscribers(ws_event=ws_event, payload=payload)


    async def _route_fanout_on_write(
        self,
        ws_event: WsEvent,
        payload: dict[str, Any],
    ) -> None:
        with_offline_signal = ws_event.event_name in OFFLINE_SIGNAL_EVENT_NAMES
        offline_user_ids: list[int] = []

        async for member_ids in self.chat_repository.iter_member_ids(
            chat_id=ws_event.chat_id,
            batch_size=chat_config.DELIVERY_ROUTER_MEMBER_BATCH_SIZE,
        ):
            for lookup_batch in chunks(member_ids, chat_config.DELIVERY_ROUTER_ROUTE_LOOKUP_BATCH_SIZE):
                routes = await self._lookup_online_routes(lookup_batch)

                if with_offline_signal:
                    offline_user_ids.extend(
                        self._offline_recipients(ws_event, lookup_batch, routes)
                    )

                await self._enqueue_gateway_deliveries(
                    routes,
                    ws_event,
                    payload,
                    require_subscription=False,
                )

        if offline_user_ids:
            await self._publish_offline_signal(ws_event, offline_user_ids)

    async def _route_to_active_subscribers(
        self,
        ws_event: WsEvent,
        payload: dict[str, Any],
    ) -> None:
        async for routes_by_gateway in self._iter_active_subscriber_routes(str(ws_event.chat_id)):
            await self._enqueue_gateway_deliveries(
                routes_by_gateway,
                ws_event,
                payload,
                require_subscription=True,
            )

    async def _route_to_removed_member(
        self,
        ws_event: WsEvent,
        payload: dict[str, Any],
    ) -> None:
        field = MEMBER_REMOVED_EVENT_FIELDS.get(ws_event.event_name)
        if field is None:
            return

        if ws_event.event_name == "chats.member.banned" and not ws_event.delta.get("ban"):
            return

        target_user_id = ws_event.delta.get(field)
        if target_user_id is None:
            return

        routes = await self._lookup_online_routes([int(target_user_id)])
        await self._enqueue_gateway_deliveries(
            routes,
            ws_event,
            payload,
            require_subscription=False,
        )

    @staticmethod
    def _offline_recipients(
        ws_event: WsEvent,
        lookup_batch: Iterable[int],
        routes: RouteMap,
    ) -> list[int]:
        online_user_ids: set[int] = set()
        for gateway_users in routes.values():
            online_user_ids |= gateway_users

        sender_id = ws_event.delta.get("sender_id")
        return sorted(set(lookup_batch) - online_user_ids - {sender_id})

    async def _publish_offline_signal(
        self,
        ws_event: WsEvent,
        offline_user_ids: list[int],
    ) -> None:
        await self.broker.send_data(
            key=str(ws_event.chat_id),
            topic=chat_config.CHAT_OFFLINE_DELIVERY_TOPIC,
            data={
                "event_id": ws_event.event_id,
                "event_name": ws_event.event_name,
                "chat_id": str(ws_event.chat_id),
                "message_id": ws_event.delta["message_id"],
                "sender_id": ws_event.delta["sender_id"],
                "offline_user_ids": offline_user_ids,
                "occurred_at": ws_event.ts,
            },
        )

        DELIVERY_ROUTER_OFFLINE_SIGNALS.labels(result="ok").inc()

    async def _lookup_online_routes(self, user_ids: Iterable[int]) -> RouteMap:
        ids = [int(user_id) for user_id in user_ids]
        if not ids:
            return {}

        pipe = self.redis.pipeline(transaction=False)

        for user_id in ids:
            pipe.smembers(WebsocketKeys.user_route_key(user_id))

        results = await pipe.execute()

        routes_by_gateway: RouteMap = {}
        stale_routes_by_user: list[tuple[int, str]] = []

        for user_id, route_set in zip(ids, results, strict=False):
            for route in route_set or ():
                gateway_id, sep, connection_id = route.partition(":")
                if not sep or not gateway_id or not connection_id:
                    stale_routes_by_user.append((user_id, route))
                    continue
                routes_by_gateway.setdefault(gateway_id, set()).add(user_id)

        if stale_routes_by_user:
            asyncio.create_task(
                self._cleanup_stale_user_routes(stale_routes_by_user),
                name="ws:route:cleanup:user",
            )

        return routes_by_gateway

    async def _iter_active_subscriber_routes(self, chat_id: str) -> AsyncIterator[RouteMap]:
        key = WebsocketKeys.active_subscription_key(chat_id)
        batch: list[ActiveSubscriptionRoute] = []

        async for route in self.redis.sscan_iter(key, count=chat_config.WS_ACTIVE_SUBSCRIBER_SCAN_COUNT):
            parsed = parse_active_subscription_route(route)
            if parsed is None:
                with contextlib.suppress(Exception):
                    await self.redis.srem(key, route)
                continue

            batch.append(parsed)
            if len(batch) >= chat_config.DELIVERY_ROUTER_ACTIVE_SUBSCRIBER_SCAN_BATCH_SIZE:
                yield await self._validate_active_subscriber_batch(key, batch)
                batch = []

        if batch:
            yield await self._validate_active_subscriber_batch(key, batch)

    async def _validate_active_subscriber_batch(
        self,
        subscription_key: str,
        routes: list[ActiveSubscriptionRoute],
    ) -> RouteMap:
        pipe = self.redis.pipeline(transaction=False)
        for _user_id, _gateway_id, connection_id, _route in routes:
            pipe.exists(WebsocketKeys.connection_key(connection_id))
        alive_flags = await pipe.execute()

        stale: list[str] = []
        routes_by_gateway: RouteMap = {}
        for (user_id, gateway_id, _connection_id, route), alive in zip(routes, alive_flags, strict=False):
            if alive:
                routes_by_gateway.setdefault(gateway_id, set()).add(user_id)
            else:
                stale.append(route)

        if stale:
            asyncio.create_task(
                self.redis.srem(subscription_key, *stale),  # pyright: ignore[reportArgumentType]
                name="ws:sub:cleanup:stale",
            )

        return routes_by_gateway

    async def _enqueue_gateway_deliveries(
        self,
        routes_by_gateway: RouteMap,
        ws_event: WsEvent,
        payload: dict[str, Any],
        *,
        require_subscription: bool,
    ) -> None:
        if not routes_by_gateway:
            return

        pipe = self.redis.pipeline(transaction=False)
        enqueued = 0

        for gateway_id, user_ids in routes_by_gateway.items():
            stream_key = WebsocketKeys.gateway_stream_key(gateway_id)
            for user_chunk in chunks(sorted(user_ids), app_config.WS_GATEWAY_STREAM_USERS_PER_ENTRY):
                stream_event = DeliveryDTO(
                    type=ws_event.type,
                    payload=payload,
                    delivery=DeliveryData(
                        require_subscription=require_subscription, recipients=user_chunk
                    ),
                    ts=ws_event.ts,
                    channel=str(ws_event.chat_id)
                )
                pipe.xadd(
                    stream_key,
                    fields={"event": stream_event.model_dump_json()},
                    maxlen=app_config.WS_GATEWAY_STREAM_MAXLEN,
                    approximate=True,
                )
                enqueued += 1

        if not enqueued:
            return

        await pipe.execute()
        DELIVERY_ROUTER_STREAM_ENTRIES.labels(strategy=ws_event.fanout_strategy.value).inc(enqueued)

    async def _cleanup_stale_user_routes(self, stale_routes_by_user: list[tuple[int, str]]) -> None:
        pipe = self.redis.pipeline(transaction=False)
        for user_id, route in stale_routes_by_user:
            pipe.srem(WebsocketKeys.user_route_key(user_id), route)
        with contextlib.suppress(Exception):
            await pipe.execute()


def parse_active_subscription_route(route: str) -> ActiveSubscriptionRoute | None:
    user_id_str, sep1, rest = route.partition(":")
    gateway_id, sep2, connection_id = rest.partition(":")
    if not sep1 or not sep2 or not user_id_str or not gateway_id or not connection_id:
        return None
    try:
        return int(user_id_str), gateway_id, connection_id, route
    except ValueError:
        return None
