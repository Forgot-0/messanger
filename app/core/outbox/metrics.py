from prometheus_client import Counter

OUTBOX_EVENTS_WRITTEN = Counter(
    "outbox_events_written_total",
    "Total number of domain events written to the outbox",
    labelnames=("topic", "event_name"),
)

OUTBOX_CLEANUP_DELETED = Counter(
    "outbox_cleanup_deleted_total",
    "Total number of outbox rows deleted by the retention cleanup task",
)
