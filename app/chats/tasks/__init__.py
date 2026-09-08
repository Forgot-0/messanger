from taskiq import AsyncBroker

from app.chats.tasks.success_attachment import AttachmentProccessTask


def register_chat_tasks(broker: AsyncBroker) -> None:
    broker.register_task(AttachmentProccessTask.run, AttachmentProccessTask.get_name())
