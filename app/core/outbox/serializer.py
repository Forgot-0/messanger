import json
from dataclasses import asdict
from typing import Any

from app.core.api.schemas import additionally_serialize
from app.core.events.event import BaseEvent


def event_to_payload(event: BaseEvent) -> dict[str, Any]:
    data = asdict(event)
    data.pop("event_id", None)
    data.pop("created_at", None)
    return json.loads(
        json.dumps(data, default=additionally_serialize)
    )
