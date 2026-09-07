from collections.abc import Iterable
from dataclasses import dataclass

from app.core.events.event import BaseEvent
from app.core.events.service import BaseEventBus
from app.core.outbox.metrics import OUTBOX_EVENTS_WRITTEN
from app.core.outbox.model import OutboxMessage
from app.core.outbox.repository import OutboxRepository
from app.core.outbox.serializer import event_to_payload


@dataclass(eq=False)
class MediatorEventBus(BaseEventBus):
    outbox_repository: OutboxRepository

    async def publish(self, events: Iterable[BaseEvent]) -> None:
        for event in events:
            outbox = OutboxMessage.create(
                aggregate_id=event.get_partition_key(),
                event_name=event.get_name(),
                payload=event_to_payload(event)
            )
            await self.outbox_repository.create(outbox)

            OUTBOX_EVENTS_WRITTEN.labels(
                topic=outbox.topic, event_name=outbox.event_name
            ).inc()
