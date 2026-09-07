from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject
from taskiq import AsyncBroker

from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask
from app.profiles.commands.profiles.proccess_avatar import ProccessAvatarCommand


def register_profiles_tasks(broker: AsyncBroker) -> None:
    broker.register_task(
        AvatarUploadTask.run, AvatarUploadTask.get_name()
    )


@dataclass
class AvatarUploadTask(BaseTask):
    __task_name__ = "avatar.resize"

    @staticmethod
    @inject
    async def run(
        user_id: int,
        key_base: str,
        mediator: FromDishka[BaseMediator],
    ) -> None:
        await mediator.handle_command(
            ProccessAvatarCommand(
                user_id=user_id,
                file_key=key_base
            )
        )
