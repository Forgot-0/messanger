import logging
from dataclasses import dataclass
from datetime import timedelta

from dishka.integrations.taskiq import FromDishka, inject

from app.chats.config import chat_config
from app.chats.repositories.reads import ReadReceiptRepository
from app.core.services.queues.task import BaseTask
from app.core.utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class ReadMarksCleanupTask(BaseTask):
    __task_name__ = "chats.read_marks.cleanup"

    @staticmethod
    @inject
    async def run(read_receipt_repository: FromDishka[ReadReceiptRepository]) -> None:
        threshold = now_utc() - timedelta(days=chat_config.READ_MARKS_RETENTION_DAYS)
        batch_size = chat_config.READ_MARKS_CLEANUP_BATCH_SIZE

        total_deleted = 0
        for _ in range(chat_config.READ_MARKS_CLEANUP_MAX_BATCHES):
            deleted = await read_receipt_repository.cleanup_marks_older_than(threshold, batch_size)
            total_deleted += deleted
            if deleted < batch_size:
                break

        logger.info(
            "Read marks cleanup finished",
            extra={"deleted": total_deleted, "threshold": threshold.isoformat()},
        )
