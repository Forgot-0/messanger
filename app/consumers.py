import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from dishka.integrations.faststream import FastStreamProvider, setup_dishka
from faststream import ContextRepo
from faststream.asgi import AsgiFastStream
from faststream.kafka import KafkaBroker
from faststream.kafka.prometheus import KafkaPrometheusMiddleware
from prometheus_client import CollectorRegistry, make_asgi_app

from app.auth.consumers import user as auth_user
from app.chats.consumers import delivery, profiles
from app.chats.services.reaction_coalescer import ReactionCoalesceQueue
from app.chats.tasks.coalescer import run_reaction_coalescer
from app.core.configs.app import app_config
from app.core.di.container import create_container
from app.core.log.init import configure_logging
from app.core.message_brokers.base import BaseMessageBroker
from app.notifications.consumers import chat_offline_delivery
from app.profiles.consumers import user

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(context: ContextRepo) -> AsyncGenerator[None]:
    logger.info("Starting FastStream")
    container = context.get("container__")
    message_broker: BaseMessageBroker = await container.get(BaseMessageBroker)
    await message_broker.start()

    coalescer_task: asyncio.Task | None = None
    coalesce_queue = await container.get(ReactionCoalesceQueue)
    coalescer_task = asyncio.create_task(
        run_reaction_coalescer(container, coalesce_queue),
        name="chats:reaction-coalescer",
    )

    yield

    if coalescer_task is not None:
        coalescer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await coalescer_task

    await message_broker.close()


def setup_router(broker: KafkaBroker) -> None:
    broker.include_router(auth_user.router)
    broker.include_router(delivery.router)
    broker.include_router(profiles.router)
    broker.include_router(user.router)
    broker.include_router(chat_offline_delivery.router)


def init_app() -> AsgiFastStream:
    configure_logging()
    registry = CollectorRegistry()
    log = structlog.get_logger("main")
    broker = KafkaBroker(
        app_config.BROKER_URL,
        client_id=app_config.GROUP_ID,
        middlewares=(
            KafkaPrometheusMiddleware(registry=registry),
        ),
        logger=log
    )
    app = AsgiFastStream(
        broker,
        lifespan=lifespan,
        asgi_routes=[
            ("/metrics", make_asgi_app(registry)),
        ],
        logger=log
    )

    setup_router(broker)
    container = create_container(FastStreamProvider())
    app.context.set_global("container__", container)

    setup_dishka(container=container, broker=broker, auto_inject=True)

    logger.info("Init app FastStream")
    return app


app = init_app()
