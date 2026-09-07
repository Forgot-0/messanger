from taskiq import AsyncBroker

from app.notifications.tasks.push_offline_recipients import PushOfflineRecipientsTask


def register_notification_tasks(broker: AsyncBroker) -> None:
    broker.register_task(
        PushOfflineRecipientsTask.run,
        PushOfflineRecipientsTask.get_name(),
    )
