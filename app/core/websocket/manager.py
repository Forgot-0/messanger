import asyncio
import contextlib
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import orjson
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.configs.app import app_config
from app.core.metrics import (
    EVICTION_REASON_CONNECTION_LIMIT,
    EVICTION_REASON_SHUTDOWN,
    EVICTION_REASON_SLOW_CONSUMER,
    WS_ACTIVE_CONNECTIONS,
    WS_ACTIVE_SUBSCRIPTIONS,
    WS_CONNECTION_EVICTIONS,
    WS_DELIVERY_LATENCY,
    WS_GATEWAY_STREAM_CLAIMED,
    WS_GATEWAY_STREAM_LENGTH,
    WS_GATEWAY_STREAM_PENDING,
)
from app.core.utils import now_utc
from app.core.websocket.dtos import DeliveryDTO
from app.core.websocket.keys import WebsocketKeys
from app.core.websocket.presence import PresenceService
from app.core.websocket.websocket import WSConnection

logger = logging.getLogger(__name__)

_LOCAL_SEND_BATCH_SIZE = 1_024
_CLAIM_START_ID = "0-0"


def default_gateway_id() -> str:
    host = os.getenv("GATEWAY_ID") or os.getenv("HOSTNAME") or "local-gateway"
    return f"{host}-{os.getpid()}"



@dataclass(slots=True)
class ConnectionManager:
    redis: Redis
    presence_service: PresenceService
    gateway_id: str = field(default_factory=default_gateway_id)
    connections_by_id: dict[str, WSConnection] = field(default_factory=dict)
    connections_by_user: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def stream_key(self) -> str:
        return WebsocketKeys.gateway_stream_key(self.gateway_id)

    @property
    def stream_group(self) -> str:
        return f"ws-gateway-{self.gateway_id}"

    @property
    def stream_consumer(self) -> str:
        return self.gateway_id

    async def startup(self) -> None:
        self._shutdown_event.clear()
        tasks = [
            asyncio.create_task(self._refresh_routes_loop(), name=f"ws:routes:{self.gateway_id}"),
            asyncio.create_task(self._consume_gateway_stream_loop(), name=f"ws:stream:{self.gateway_id}"),
            asyncio.create_task(self._claim_pending_loop(), name=f"ws:claim:{self.gateway_id}"),
            asyncio.create_task(self._stream_metrics_loop(), name=f"ws:metrics:{self.gateway_id}"),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        self._shutdown_event.set()
        async with self._lock:
            conns = list(self.connections_by_id.values())

        for conn in conns:
            WS_CONNECTION_EVICTIONS.labels(
                gateway_id=self.gateway_id, reason=EVICTION_REASON_SHUTDOWN
            ).inc()
            await self.unregister(conn, close_code=1001, close_reason="server shutdown")

        gateway_connections = await self.redis.smembers(
            WebsocketKeys.gateway_route_key(self.gateway_id)
        )
        if gateway_connections:
            pipe = self.redis.pipeline(transaction=False)
            for cid in gateway_connections:
                pipe.delete(WebsocketKeys.connection_key(cid)) # pyright: ignore[reportArgumentType]
            pipe.delete(WebsocketKeys.gateway_route_key(self.gateway_id))
            await pipe.execute()

        self._export_state_metrics()
        logger.info("ChannelConnectionManager shut down")

    async def register(self, conn: WSConnection) -> None:
        conn.gateway_id = self.gateway_id

        stale_to_close: list[WSConnection] = []
        async with self._lock:
            self.connections_by_id[conn.connection_id] = conn
            user_conns = self.connections_by_user[conn.user_id]
            user_conns.add(conn.connection_id)
            is_first_local_connection = len(user_conns) == 1

            overflow = len(user_conns) - app_config.WS_MAX_CONNECTIONS_PER_USER
            if overflow > 0:
                stale_to_close.extend(
                    sorted((
                        self.connections_by_id[cid]
                        for cid in user_conns
                        if cid in self.connections_by_id
                    ),
                    key=lambda c: c.connected_at,
                    )[:overflow]
                )

        await self.set_route_users(conn)
        await conn.start()

        if is_first_local_connection:
            await self.presence_service.set_online(conn.user_id)

        for stale in stale_to_close:
            if stale.connection_id == conn.connection_id:
                continue
            WS_CONNECTION_EVICTIONS.labels(
                gateway_id=self.gateway_id, reason=EVICTION_REASON_CONNECTION_LIMIT
            ).inc()
            asyncio.create_task(
                self.unregister(stale, close_code=1012, close_reason="connection limit exceeded"),
                name=f"ws:evict:{stale.connection_id}",
            )

        self._export_state_metrics()
        logger.debug(
            "WebSocket registered",
            extra={"connection_id": conn.connection_id, "user_id": conn.user_id},
        )

    async def unregister(
        self,
        conn: WSConnection,
        *,
        close_code: int = 1000,
        close_reason: str = "",
    ) -> None:
        async with self._lock:
            self.connections_by_id.pop(conn.connection_id, None)
            user_conns = self.connections_by_user.get(conn.user_id)
            if user_conns is not None:
                user_conns.discard(conn.connection_id)
                if not user_conns:
                    self.connections_by_user.pop(conn.user_id, None)

            subscribed_channels = set(conn.subscriptions)
            for channel in subscribed_channels:
                self._unsubscribe_channel_in_memory(conn, channel)

        route_value = f"{self.gateway_id}:{conn.connection_id}"
        sub_route = WebsocketKeys.active_subscription_route(conn.user_id, self.gateway_id, conn.connection_id)

        pipe = self.redis.pipeline(transaction=False)
        pipe.srem(WebsocketKeys.user_route_key(conn.user_id), route_value)
        pipe.srem(WebsocketKeys.gateway_route_key(self.gateway_id), conn.connection_id)
        pipe.delete(WebsocketKeys.connection_key(conn.connection_id))
        for channel in subscribed_channels:
            pipe.srem(WebsocketKeys.active_subscription_key(channel), sub_route)
            pipe.delete(WebsocketKeys.connection_subscription_key(conn.connection_id, channel))

        pipe.scard(WebsocketKeys.user_route_key(conn.user_id))
        results = await pipe.execute()

        remaining_routes = self._as_int(results[-1] if results else 0)
        if remaining_routes <= 0:
            await self.presence_service.set_offline(conn.user_id)

        await conn.close(code=close_code, reason=close_reason)

        self._export_state_metrics()
        logger.debug(
            "WebSocket unregistered",
            extra={
                "connection_id": conn.connection_id,
                "user_id": conn.user_id,
                "subscriptions": len(subscribed_channels),
                "remaining_routes": remaining_routes,
            },
        )

    async def subscribe_channel(self, conn: WSConnection, channel: str) -> None:
        async with self._lock:
            conn.subscriptions.add(channel)

        route = WebsocketKeys.active_subscription_route(conn.user_id, self.gateway_id, conn.connection_id)
        pipe = self.redis.pipeline(transaction=False)
        pipe.sadd(WebsocketKeys.active_subscription_key(channel), route)
        pipe.expire(WebsocketKeys.active_subscription_key(channel), app_config.WS_ACTIVE_SUBSCRIPTION_TTL)
        pipe.set(
            WebsocketKeys.connection_subscription_key(conn.connection_id, channel),
            route,
            ex=app_config.WS_ACTIVE_SUBSCRIPTION_TTL,
        )
        await pipe.execute()
        self._export_state_metrics()

    async def unsubscribe_channel(self, conn: WSConnection, channel: str) -> None:
        async with self._lock:
            self._unsubscribe_channel_in_memory(conn, channel)

        route = WebsocketKeys.active_subscription_route(conn.user_id, self.gateway_id, conn.connection_id)
        pipe = self.redis.pipeline(transaction=False)
        pipe.srem(WebsocketKeys.active_subscription_key(channel), route)
        pipe.delete(WebsocketKeys.connection_subscription_key(conn.connection_id, channel))
        await pipe.execute()
        self._export_state_metrics()

    async def send_to_users_local(
        self,
        event: DeliveryDTO,
    ) -> None:
        async with self._lock:
            conns = [
                conn
                for uid in event.delivery.recipients
                for conn_id in tuple(self.connections_by_user.get(uid, ()))
                if (conn := self.connections_by_id.get(conn_id)) is not None
                and (not event.delivery.require_subscription or event.channel in conn.subscriptions)
            ]

        await self._send_to_connections(conns, event)

    async def _send_to_connections(self, conns: list[WSConnection], event: DeliveryDTO) -> None:
        if not conns:
            return

        for start in range(0, len(conns), _LOCAL_SEND_BATCH_SIZE):
            batch = conns[start:start + _LOCAL_SEND_BATCH_SIZE]
            await asyncio.gather(
                *(self._send_or_unregister(conn, event) for conn in batch),
                return_exceptions=False,
            )

    async def _send_or_unregister(self, conn: WSConnection, event: DeliveryDTO) -> None:
        if conn.try_send({
            "type": event.type,
            "channel": event.channel,
            "payload": event.payload,
            "ts": event.ts
        }):
            self._observe_delivery_latency(event)
            return

        WS_CONNECTION_EVICTIONS.labels(
            gateway_id=self.gateway_id, reason=EVICTION_REASON_SLOW_CONSUMER
        ).inc()
        logger.warning(
            "Dropping slow WebSocket consumer",
            extra={"connection_id": conn.connection_id, "user_id": conn.user_id},
        )
        asyncio.create_task(
            self.unregister(conn, close_code=1013, close_reason="slow consumer"),
            name=f"ws:drop:{conn.connection_id}",
        )

    def _observe_delivery_latency(self, event: DeliveryDTO) -> None:
        event_ts = datetime.fromisoformat(event.ts)

        latency = (now_utc() - event_ts).total_seconds()
        if latency < 0:
            return
        WS_DELIVERY_LATENCY.labels(gateway_id=self.gateway_id).observe(latency)

    async def set_route_users(self, conn: WSConnection) -> None:
        route_value = f"{self.gateway_id}:{conn.connection_id}"
        pipe = self.redis.pipeline(transaction=False)
        pipe.sadd(WebsocketKeys.user_route_key(conn.user_id), route_value)
        pipe.expire(WebsocketKeys.user_route_key(conn.user_id), app_config.WS_REDIS_CONNECTION_TTL)
        pipe.sadd(WebsocketKeys.gateway_route_key(self.gateway_id), conn.connection_id)
        pipe.expire(WebsocketKeys.gateway_route_key(self.gateway_id), app_config.WS_REDIS_CONNECTION_TTL)
        pipe.set(
            WebsocketKeys.connection_key(conn.connection_id),
            orjson.dumps(
                {
                    "user_id": conn.user_id,
                    "gateway_id": self.gateway_id,
                    "device_id": conn.device_id,
                    "connected_at": conn.connected_at.isoformat(),
                }
            ),
            ex=app_config.WS_REDIS_CONNECTION_TTL,
        )
        await pipe.execute()

    async def _refresh_routes_loop(self) -> None:
        interval = max(5, min(30, app_config.WS_REDIS_CONNECTION_TTL // 2))
        tick = 0
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=float(interval))
                break
            except TimeoutError:
                pass

            tick += 1
            try:
                await self.redis.expire(self.stream_key, app_config.WS_REDIS_CONNECTION_TTL)

                async with self._lock:
                    conns = list(self.connections_by_id.values())
                    subs_snapshot = {conn.connection_id: set(conn.subscriptions) for conn in conns}

                for conn in conns:
                    if conn.closed:
                        await self.unregister(conn)
                        continue

                    await self.set_route_users(conn)

                    subscriptions = subs_snapshot.get(conn.connection_id, set())
                    if subscriptions:
                        route = WebsocketKeys.active_subscription_route(conn.user_id, self.gateway_id, conn.connection_id)
                        pipe = self.redis.pipeline(transaction=False)
                        for channel in subscriptions:
                            pipe.sadd(WebsocketKeys.active_subscription_key(channel), route)
                            pipe.expire(
                                WebsocketKeys.active_subscription_key(channel),
                                app_config.WS_ACTIVE_SUBSCRIPTION_TTL
                            )
                            pipe.set(
                                WebsocketKeys.connection_subscription_key(conn.connection_id, channel),
                                route,
                                ex=app_config.WS_ACTIVE_SUBSCRIPTION_TTL,
                            )
                        await pipe.execute()

                await self._refresh_presence(conns)
                if tick % app_config.WS_PRESENCE_CLEANUP_EVERY_TICKS == 0:
                    await self.presence_service.cleanup_stale()

                self._export_state_metrics()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("WebSocket route refresh failed")

    async def _refresh_presence(self, conns: list[WSConnection]) -> None:
        user_ids = {conn.user_id for conn in conns if not conn.closed}
        if not user_ids:
            return
        await self.presence_service.refresh(user_ids)

    async def _ensure_stream_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                name=self.stream_key,
                groupname=self.stream_group,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _consume_gateway_stream_loop(self) -> None:
        consecutive_errors = 0
        await self._ensure_stream_group()

        with contextlib.suppress(Exception):
            await self._claim_pending_entries()

        while not self._shutdown_event.is_set():
            try:
                messages = await self.redis.xreadgroup(
                    groupname=self.stream_group,
                    consumername=self.stream_consumer,
                    streams={self.stream_key: ">"},
                    count=app_config.WS_GATEWAY_STREAM_READ_COUNT,
                    block=app_config.WS_GATEWAY_STREAM_BLOCK_MS,
                )
                consecutive_errors = 0

                if not messages:
                    continue

                entries = [
                    (message_id, fields)
                    for _stream_name, stream_messages in messages
                    for message_id, fields in stream_messages # pyright: ignore[reportGeneralTypeIssues]
                ]
                await self._process_entries(entries)

            except asyncio.CancelledError:
                raise
            except Exception:
                consecutive_errors += 1
                backoff = min(consecutive_errors * 0.5, 10.0)
                logger.exception(
                    "WebSocket gateway stream consumer error; retrying in %.1fs",
                    backoff,
                )
                await asyncio.sleep(backoff)

    async def _claim_pending_loop(self) -> None:
        interval = float(app_config.WS_GATEWAY_STREAM_CLAIM_INTERVAL)
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                break
            except TimeoutError:
                pass

            try:
                await self._claim_pending_entries()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to claim pending gateway stream entries")

    async def _claim_pending_entries(self) -> int:
        await self._ensure_stream_group()

        claimed_total = 0
        cursor: Any = _CLAIM_START_ID
        while not self._shutdown_event.is_set():
            result = await self.redis.xautoclaim(
                name=self.stream_key,
                groupname=self.stream_group,
                consumername=self.stream_consumer,
                min_idle_time=app_config.WS_GATEWAY_STREAM_CLAIM_MIN_IDLE_MS,
                start_id=cursor,
                count=app_config.WS_GATEWAY_STREAM_CLAIM_COUNT,
            )

            next_cursor, entries = result[0], result[1]
            if entries:
                claimed_total += len(entries)
                WS_GATEWAY_STREAM_CLAIMED.labels(gateway_id=self.gateway_id).inc(len(entries))
                await self._process_entries(list(entries))

            cursor = _decode(next_cursor)
            if not cursor or cursor == _CLAIM_START_ID or not entries:
                break

        if claimed_total:
            logger.info(
                "Reclaimed pending websocket gateway stream entries",
                extra={"claimed": claimed_total},
            )
        return claimed_total

    async def _process_entries(self, entries: list[Any]) -> None:
        if not entries:
            return

        results = await asyncio.gather(
            *(self._process_gateway_stream_entry(message_id, fields) for message_id, fields in entries),
            return_exceptions=True,
        )

        ack_ids: list[Any] = []
        for (message_id, _fields), result in zip(entries, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "Failed to process websocket gateway stream message",
                    exc_info=result,
                    extra={"stream_id": message_id},
                )
                continue
            ack_ids.append(message_id)

        if ack_ids:
            await self.redis.xack(self.stream_key, self.stream_group, *ack_ids)

    async def _stream_metrics_loop(self) -> None:
        interval = float(app_config.WS_GATEWAY_STREAM_METRICS_INTERVAL)
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                break
            except TimeoutError:
                pass

            try:
                await self.export_stream_metrics()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to export websocket gateway stream metrics")

    async def export_stream_metrics(self) -> None:
        length = await self.redis.xlen(self.stream_key)
        WS_GATEWAY_STREAM_LENGTH.labels(gateway_id=self.gateway_id).set(float(length or 0))

        with contextlib.suppress(ResponseError):
            summary = await self.redis.xpending(self.stream_key, self.stream_group)
            pending = summary.get("pending", 0) if isinstance(summary, dict) else 0
            WS_GATEWAY_STREAM_PENDING.labels(gateway_id=self.gateway_id).set(float(pending or 0))

        self._export_state_metrics()

    async def _process_gateway_stream_entry(self, message_id: Any, fields: dict[Any, Any]) -> Any:
        event = DeliveryDTO.model_validate_json(fields["event"])
        await self.send_to_users_local(event)
        return message_id

    async def send_user_payload(self, event: DeliveryDTO) -> None:
        routes: set[str] = await self.redis.smembers(
            WebsocketKeys.user_route_key(event.delivery.recipients[0])
        ) # pyright: ignore[reportAssignmentType]

        gateways: set[str] = set()
        for raw in routes or ():
            gateway_id, _sep, connection_id = raw.partition(":")
            if gateway_id and connection_id:
                gateways.add(gateway_id)

        if not gateways:
            return

        pipe = self.redis.pipeline(transaction=False)
        for gateway_id in gateways:
            pipe.xadd(
                WebsocketKeys.gateway_stream_key(gateway_id),
                fields={
                    "event": event.model_dump_json(),
                },
                maxlen=app_config.WS_GATEWAY_STREAM_MAXLEN,
                approximate=True,
            )
        await pipe.execute()

    def _export_state_metrics(self) -> None:
        WS_ACTIVE_CONNECTIONS.labels(gateway_id=self.gateway_id).set(len(self.connections_by_id))
        WS_ACTIVE_SUBSCRIPTIONS.labels(gateway_id=self.gateway_id).set(
            sum(len(conn.subscriptions) for conn in self.connections_by_id.values())
        )

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _unsubscribe_channel_in_memory(self, conn: WSConnection, channel: str) -> None:
        conn.subscriptions.discard(channel)


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value) if value is not None else ""
