from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject

from app.chats.commands.attachments.sweep_transcodes import SweepStaleTranscodesCommand
from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask


@dataclass
class AttachmentTranscodeSweepTask(BaseTask):
    __task_name__ = "chats.attachment.transcode_sweep"

    @staticmethod
    @inject
    async def run(mediator: FromDishka[BaseMediator]) -> None:
        await mediator.handle_command(SweepStaleTranscodesCommand())
