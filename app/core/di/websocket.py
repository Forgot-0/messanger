from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from app.core.websocket.manager import ConnectionManager
from app.core.websocket.presence import PresenceService


class CoreWSProvider(Provider):
    @provide(scope=Scope.APP)
    def presence_service(self, redis: Redis) -> PresenceService:
        return PresenceService(redis=redis)

    @provide(scope=Scope.APP)
    def connection_manager(self, redis: Redis, presence: PresenceService) -> ConnectionManager:
        return ConnectionManager(redis=redis, presence_service=presence)
