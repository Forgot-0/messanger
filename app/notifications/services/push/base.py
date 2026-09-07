from abc import ABC, abstractmethod

from app.notifications.models.notification import Notification


class PushService(ABC):
    @abstractmethod
    async def push(self, notification: Notification) -> None:
        ...
