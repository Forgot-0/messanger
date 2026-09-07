from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.events.event import BaseEvent


@dataclass(slots=True)
class BrokerRecord:
    topic: str
    key: bytes
    value: bytes
    headers: list[tuple[str, bytes]] = field(default_factory=list)


@dataclass
class BaseMessageBroker(ABC):

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def send_message(self, key: bytes, topic: str, value: bytes) -> None:
        ...

    @abstractmethod
    async def send_data(self, key: str, topic: str, data: dict[str, Any]) -> None:
        ...

    @abstractmethod
    async def send_event(self, key: str, topic: str, event: BaseEvent) -> None:
        ...

    @abstractmethod
    async def send_many(self, records: Sequence[BrokerRecord]) -> list[BaseException | None]:
        ...

    @abstractmethod
    def start_consuming(self, topic: list[str]) -> AsyncIterator[dict]:
        ...

    @abstractmethod
    async def stop_consuming(self) -> None:
        ...
