from prometheus_client import Counter, Gauge, Histogram

WS_ACTIVE_CONNECTIONS = Gauge(
    "chat_ws_active_connections",
    "Number of live WebSocket connections served by this gateway process",
    labelnames=("gateway_id",),
)

WS_ACTIVE_SUBSCRIPTIONS = Gauge(
    "chat_ws_active_subscriptions",
    "Number of (connection, chat) subscriptions held by this gateway process",
    labelnames=("gateway_id",),
)

WS_CONNECTION_EVICTIONS = Counter(
    "chat_ws_connection_evictions_total",
    "WebSocket connections force-closed by the gateway, by reason",
    labelnames=("gateway_id", "reason"),
)

WS_GATEWAY_STREAM_LENGTH = Gauge(
    "chat_ws_gateway_stream_length",
    "XLEN of the Redis Stream owned by this gateway",
    labelnames=("gateway_id",),
)

WS_GATEWAY_STREAM_PENDING = Gauge(
    "chat_ws_gateway_stream_pending",
    "Number of pending (delivered but not acked) entries in the gateway consumer group",
    labelnames=("gateway_id",),
)

WS_GATEWAY_STREAM_CLAIMED = Counter(
    "chat_ws_gateway_stream_claimed_total",
    "Stream entries reclaimed from dead consumers via XAUTOCLAIM",
    labelnames=("gateway_id",),
)

WS_DELIVERY_LATENCY = Histogram(
    "chat_ws_delivery_latency_seconds",
    "End-to-end latency between the domain event time (`ts`) and the moment the "
    "event was enqueued to a concrete WebSocket connection (`enqueued_at`)",
    labelnames=("gateway_id",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)


EVICTION_REASON_CONNECTION_LIMIT = "connection_limit"
EVICTION_REASON_SLOW_CONSUMER = "slow_consumer"
EVICTION_REASON_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
EVICTION_REASON_SHUTDOWN = "shutdown"
EVICTION_REASON_CLIENT = "client"
