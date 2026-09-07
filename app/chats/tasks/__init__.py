from taskiq import AsyncBroker

from app.chats.tasks.backfill_profiles import BackfillChatProfilesTask
from app.chats.tasks.success_attachment import AttachmentProccessTask


def register_chat_tasks(broker: AsyncBroker) -> None:
    broker.register_task(AttachmentProccessTask.run, AttachmentProccessTask.get_name())
    broker.register_task(BackfillChatProfilesTask.run, BackfillChatProfilesTask.get_name())
