from app.core.configs.base import BaseConfig


class NotificationConfig(BaseConfig):
    CHAT_OFFLINE_DELIVERY_TOPIC: str = "chats.offline-delivery"

    OFFLINE_PUSH_GROUP_ID: str = "offline-push"
    OFFLINE_PUSH_MAX_CONCURRENCY: int = 32
    FIREBASE_CREDENTIALS_PATH: str = ""


    FIREBASE_APP_NAME: str = "notifications-push"
    FIREBASE_SEND_BATCH_LIMIT: int = 500
    PUSH_DEFAULT_TITLE: str = "Новое сообщение"


notification_config = NotificationConfig()

