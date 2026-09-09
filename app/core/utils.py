import time
from datetime import UTC, datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def fromtimestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)

def now_ms() -> int:
    return int(time.time() * 1000)

