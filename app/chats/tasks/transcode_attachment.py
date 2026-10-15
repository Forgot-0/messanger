from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject

from app.chats.commands.attachments.transcode import TranscodeAttachmentCommand
from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask


@dataclass
class AttachmentTranscodeTask(BaseTask):
    __task_name__ = "chats.attachment.transcode"

    @staticmethod
    @inject
    async def run(attachment_id: str, mediator: FromDishka[BaseMediator]) -> None:
        await mediator.handle_command(TranscodeAttachmentCommand(attachment_id=attachment_id))
