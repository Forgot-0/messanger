from dishka import Provider, Scope, decorate, provide, provide_all
from firebase_admin import App

from app.core.mediators.base import CommandRegistry, QueryRegistry
from app.notifications.commands.devices.create import (
    CreateUserDeviceCommand,
    CreateUserDeviceCommandHandler,
)
from app.notifications.commands.notifications.mark_all_read import (
    MarkAllNotificationsAsReadCommand,
    MarkAllNotificationsAsReadCommandHandler,
)
from app.notifications.commands.notifications.mark_read import (
    MarkNotificationAsReadCommand,
    MarkNotificationAsReadCommandHandler,
)
from app.notifications.commands.notifications.push import (
    PushNotificationCommand,
    PushNotificationCommandHandler,
)
from app.notifications.config import notification_config
from app.notifications.queries.notifications.get_list import GetNotificationsQuery, GetNotificationsQueryHandler
from app.notifications.queries.notifications.get_unread_count import (
    GetUnreadNotificationsCountQuery,
    GetUnreadNotificationsCountQueryHandler,
)
from app.notifications.repositories.devices import DeviceRepository
from app.notifications.repositories.notifications import NotificationRepository
from app.notifications.services.push.base import PushService
from app.notifications.services.push.firebase.init import init_firebase_app
from app.notifications.services.push.firebase.service import FirebaseAdminPushService


class NotificationModuleProvider(Provider):
    scope = Scope.REQUEST

    notification_repository = provide(NotificationRepository)
    device_repository = provide(DeviceRepository)

    handlers = provide_all(
        MarkNotificationAsReadCommandHandler,
        MarkAllNotificationsAsReadCommandHandler,
        CreateUserDeviceCommandHandler,
        PushNotificationCommandHandler,
        GetNotificationsQueryHandler,
        GetUnreadNotificationsCountQueryHandler,
    )

    @provide(scope=Scope.APP)
    def firebase_app(self) -> App:
        return init_firebase_app(
            app_name=notification_config.FIREBASE_APP_NAME,
            credentials_path=notification_config.FIREBASE_CREDENTIALS_PATH,
        )

    @provide(scope=Scope.REQUEST)
    def push_service(
        self,
        firebase_app: App,
        device_repository: DeviceRepository,
    ) -> PushService:
        return FirebaseAdminPushService(
            firebase_app=firebase_app,
            device_repository=device_repository,
            send_batch_limit=notification_config.FIREBASE_SEND_BATCH_LIMIT,
        )

    @decorate
    def register_notification_commands(self, command_registry: CommandRegistry) -> CommandRegistry:
        command_registry.register_command(MarkNotificationAsReadCommand, MarkNotificationAsReadCommandHandler)
        command_registry.register_command(
            MarkAllNotificationsAsReadCommand,
            MarkAllNotificationsAsReadCommandHandler,
        )
        command_registry.register_command(CreateUserDeviceCommand, CreateUserDeviceCommandHandler)
        command_registry.register_command(PushNotificationCommand, PushNotificationCommandHandler)
        return command_registry

    @decorate
    def register_notification_queries(self, query_registry: QueryRegistry) -> QueryRegistry:
        query_registry.register_query(GetNotificationsQuery, GetNotificationsQueryHandler)
        query_registry.register_query(GetUnreadNotificationsCountQuery, GetUnreadNotificationsCountQueryHandler)
        return query_registry

