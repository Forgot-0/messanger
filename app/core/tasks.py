from taskiq import AsyncBroker

from app.auth.tasks import register_auth_tasks
from app.chats.tasks import register_chat_tasks
from app.core.outbox.task import register_outbox_tasks
from app.core.services.mail.aiosmtplib.task import SendEmail
from app.notifications.tasks import register_notification_tasks
from app.profiles.tasks import register_profiles_tasks


def register_tasks(broker: AsyncBroker) -> None:
    broker.register_task(
        SendEmail.run,
        task_name=SendEmail.get_name()
    )

    register_auth_tasks(broker)
    register_chat_tasks(broker)
    register_outbox_tasks(broker)
    register_notification_tasks(broker)
    register_profiles_tasks(broker)
