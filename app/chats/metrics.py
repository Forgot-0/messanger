from prometheus_client import Counter, Histogram

CHAT_REACTION_COALESCE_COLLAPSED = Histogram(
    "chat_reaction_coalesce_collapsed",
    "Number of reaction events collapsed into a single fan-out by the coalescer",
    buckets=(1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144),
)

DELIVERY_ROUTER_STREAM_ENTRIES = Counter(
    "chat_delivery_router_stream_entries_total",
    "Entries pushed by ChatDeliveryRouter into gateway Redis Streams",
    labelnames=("strategy",),
)

DELIVERY_ROUTER_OFFLINE_SIGNALS = Counter(
    "chat_delivery_router_offline_signals_total",
    "Offline-recipients signals published to the notifications topic, by result",
    labelnames=("result",),
)

ATTACHMENT_PROCESSING_SECONDS = Histogram(
    "chat_attachment_processing_seconds",
    "Time to validate, sanitize and promote one attachment, by type and outcome",
    labelnames=("attachment_type", "outcome"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)

ATTACHMENT_MEDIA_DEGRADED = Counter(
    "chat_attachment_media_degraded_total",
    "Attachments promoted without an optional derivative (poster, metadata-free remux)",
    labelnames=("stage",),
)

ATTACHMENT_TRANSCODE_SECONDS = Histogram(
    "chat_attachment_transcode_seconds",
    "Wall time of one HLS transcode, download and upload included",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 900, 1800),
)

ATTACHMENT_TRANSCODE_RESULTS = Counter(
    "chat_attachment_transcode_total",
    "HLS transcode attempts by result (ready, failed, retry, skipped, locked)",
    labelnames=("result",),
)
