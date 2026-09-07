from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject

from app.chats.commands.profiles.backfill import BackfillChatProfilesCommand
from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask


@dataclass
class BackfillChatProfilesTask(BaseTask):
    __task_name__ = "chats.profiles.backfill"

    @staticmethod
    @inject
    async def run(
        mediator: FromDishka[BaseMediator],
        batch_size: int = 500,
    ) -> None:
        await mediator.handle_command(
            BackfillChatProfilesCommand(batch_size=batch_size)
        )

