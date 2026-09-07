import logging

from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import ScheduleSource, TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisScheduleSource

from app.core.configs.app import app_config
from app.core.di.container import create_container
from app.core.log.init import configure_logging
from app.core.message_brokers.base import BaseMessageBroker
from app.core.services.queues.taskiq.init import broker

logger = logging.getLogger(__name__)

container = create_container(TaskiqProvider())
setup_dishka(container=container, broker=broker)
configure_logging()

@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(_state: TaskiqState) -> None:
    message_broker = await container.get(BaseMessageBroker)
    await message_broker.start()
    logger.info("Startup task iq")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(_state: TaskiqState) -> None:
    message_broker = await container.get(BaseMessageBroker)
    await message_broker.close()
    logger.info("Shutdown task iq")

sources: list[ScheduleSource]

if app_config.ENVIRONMENT == "testing":
    sources = [LabelScheduleSource(broker=broker)]
else:
    redis_schedule_source = RedisScheduleSource(
        url=app_config.QUEUE_REDIS_BROKER_URL,
    )
    sources = [redis_schedule_source, LabelScheduleSource(broker=broker)]


scheduler = TaskiqScheduler(
    broker=broker,
    sources=sources,
)
