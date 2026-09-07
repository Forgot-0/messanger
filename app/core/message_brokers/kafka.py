import asyncio
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any

import orjson
from aiokafka import AIOKafkaConsumer
from aiokafka.producer import AIOKafkaProducer

from app.core.events.event import BaseEvent
from app.core.message_brokers.base import BaseMessageBroker, BrokerRecord
from app.core.message_brokers.converters import convert_dict_to_broker_message, convert_event_to_broker_message


@dataclass
class KafkaMessageBroker(BaseMessageBroker):
    producer: AIOKafkaProducer
    consumer: AIOKafkaConsumer

    async def send_message(self, key: bytes, topic: str, value: bytes) -> None:
        await self.producer.send(topic=topic, key=key, value=value)

    async def send_data(self, key: str, topic: str, data: dict[str, Any]) -> None:
        data["key"] = key
        value = convert_dict_to_broker_message(data)
        fut = await self.producer.send(topic=topic, key=key.encode(), value=value)
        await fut

    async def send_event(self, key: str, topic: str, event: BaseEvent) -> None:
        value = convert_event_to_broker_message(event)
        await self.producer.send(topic=topic, key=key.encode(), value=value)

    async def send_many(self, records: Sequence[BrokerRecord]) -> list[BaseException | None]:
        results: list[BaseException | None] = [None] * len(records)
        futures: list[tuple[int, asyncio.Future[Any]]] = []

        for index, record in enumerate(records):
            try:
                future = await self.producer.send(
                    topic=record.topic,
                    key=record.key,
                    value=record.value,
                    headers=record.headers or None,
                )
            except BaseException as error:
                results[index] = error
                continue

            futures.append((index, future))

        if not futures:
            return results

        completed = await asyncio.gather(
            *(future for _, future in futures), return_exceptions=True
        )
        for (index, _), outcome in zip(futures, completed, strict=True):
            if isinstance(outcome, BaseException):
                results[index] = outcome

        return results

    async def start_consuming(self, topic: list[str]) -> AsyncGenerator[dict[str, Any]]:
        self.consumer.subscribe(topics=topic)

        async for message in self.consumer:
            yield orjson.loads(message.value) # type: ignore

    async def stop_consuming(self) -> None:
        self.consumer.unsubscribe()

    async def close(self) -> None:
        await self.consumer.stop()
        await self.producer.stop()

    async def start(self) -> None:
        await self.producer.start()
        await self.consumer.start()
