import logging
from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject
from taskiq import AsyncBroker

from app.core.configs.app import app_config
from app.core.outbox.metrics import OUTBOX_CLEANUP_DELETED
from app.core.outbox.repository import OutboxRepository
from app.core.services.queues.task import BaseTask

logger = logging.getLogger(__name__)

MAX_CLEANUP_BATCHES_PER_RUN = 50


def register_outbox_tasks(broker: AsyncBroker) -> None:
    broker.register_task(
        OutboxCleanupTask.run,
        OutboxCleanupTask.get_name(),
        schedule=[{"cron": f"*/{max(1, app_config.OUTBOX_CLEANUP_INTERVAL_SECONDS // 60)} * * * *"}],
    )


@dataclass
class OutboxCleanupTask(BaseTask):
    __task_name__ = "outbox.cleanup"

    @staticmethod
    @inject
    async def run(
        outbox_repository: FromDishka[OutboxRepository],
        retention_days: int | None = None,
    ) -> None:
        total_deleted = 0
        for _ in range(MAX_CLEANUP_BATCHES_PER_RUN):
            deleted = await outbox_repository.cleanup_older_than(
                retention_days=retention_days
            )
            total_deleted += deleted
            if deleted < app_config.OUTBOX_CLEANUP_BATCH_SIZE:
                break

        if total_deleted:
            OUTBOX_CLEANUP_DELETED.inc(total_deleted)

        logger.info(
            "Outbox cleanup finished",
            extra={
                "deleted": total_deleted,
                "retention_days": retention_days or app_config.OUTBOX_RETENTION_DAYS,
            },
        )
