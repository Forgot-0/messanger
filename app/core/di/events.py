from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.events.event import EventRegistry
from app.core.events.mediator.service import MediatorEventBus
from app.core.events.service import BaseEventBus
from app.core.outbox.repository import OutboxRepository


class EventProvider(Provider):
    scope = Scope.APP

    @provide
    def event_idempotency(self, redis: Redis) -> EventIdempotencyGuard:
        return EventIdempotencyGuard(
            redis=redis,
            ttl_seconds=7 * 24 * 3600
        )

    @provide
    def event_handler_registry(self) -> EventRegistry:
        registry = EventRegistry()
        return registry

    @provide(scope=Scope.REQUEST)
    def event_bus(
        self, event_registy: EventRegistry, outbox_repository: OutboxRepository
    ) -> BaseEventBus:
        return MediatorEventBus(
            event_registy=event_registy,
            outbox_repository=outbox_repository,
        )

