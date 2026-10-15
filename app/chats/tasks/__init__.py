from taskiq import AsyncBroker

from app.chats.config import chat_config
from app.chats.tasks.chat_avatar import ChatAvatarProcessTask
from app.chats.tasks.read_marks_cleanup import ReadMarksCleanupTask
from app.chats.tasks.success_attachment import AttachmentProccessTask
from app.chats.tasks.transcode_attachment import AttachmentTranscodeTask
from app.chats.tasks.transcode_sweep import AttachmentTranscodeSweepTask


def register_chat_tasks(broker: AsyncBroker) -> None:
    broker.register_task(AttachmentProccessTask.run, AttachmentProccessTask.get_name())
    broker.register_task(ChatAvatarProcessTask.run, ChatAvatarProcessTask.get_name())
    broker.register_task(AttachmentTranscodeTask.run, AttachmentTranscodeTask.get_name())
    broker.register_task(
        AttachmentTranscodeSweepTask.run,
        AttachmentTranscodeSweepTask.get_name(),
        schedule=[{"cron": f"*/{max(1, chat_config.VIDEO_TRANSCODE_SWEEP_INTERVAL_MINUTES)} * * * *"}],
    )
    broker.register_task(
        ReadMarksCleanupTask.run,
        ReadMarksCleanupTask.get_name(),
        schedule=[{"cron": f"*/{max(1, chat_config.READ_MARKS_CLEANUP_INTERVAL_MINUTES)} * * * *"}],
    )
