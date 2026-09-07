import logging
from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject

from app.chats.commands.attachments.proccess import ProccessAttachmentsCommand
from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask

logger = logging.getLogger(__name__)


@dataclass
class AttachmentProccessTask(BaseTask):
    __task_name__ = "chats.attachment.proccess"

    @staticmethod
    @inject
    async def run(
        chat_id: str,
        user_id: int,
        upload_tokens: list[str],
        mediator: FromDishka[BaseMediator]
    ) -> None:
        await mediator.handle_command(
            ProccessAttachmentsCommand(
                chat_id=chat_id,
                user_id=user_id,
                upload_tokens=upload_tokens
            )
        )
