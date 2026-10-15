from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject

from app.chats.commands.avatars.process import ProcessChatAvatarCommand
from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask


@dataclass
class ChatAvatarProcessTask(BaseTask):
    __task_name__ = "chats.avatar.process"

    @staticmethod
    @inject
    async def run(
        chat_id: str,
        user_id: int,
        upload_token: str,
        mediator: FromDishka[BaseMediator],
    ) -> None:
        await mediator.handle_command(
            ProcessChatAvatarCommand(
                chat_id=chat_id,
                user_id=user_id,
                upload_token=upload_token,
            )
        )
