import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from firebase_admin import App, messaging

from app.notifications.models.notification import Notification
from app.notifications.repositories.devices import DeviceRepository
from app.notifications.services.push.base import PushService

logger = logging.getLogger(__name__)


@dataclass
class FirebaseAdminPushService(PushService):
    firebase_app: App
    device_repository: DeviceRepository
    send_batch_limit: int = 500

    async def push(self, notification: Notification) -> None:
        devices = await self.device_repository.get_active_by_user_id(notification.user_id)
        if not devices:
            return

        tokens = [device.token for device in devices]
        invalid_tokens: list[str] = []

        for token_chunk in [
            list(tokens[i:i + self.send_batch_limit])
            for i in range(0, len(tokens), self.send_batch_limit)
        ]:
            message = self._build_multicast(token_chunk, notification)
            try:
                response = await asyncio.to_thread(
                    messaging.send_each_for_multicast, message, app=self.firebase_app
                )
            except Exception:
                logger.exception(
                    "Firebase multicast send failed",
                    extra={"user_id": notification.user_id, "tokens": len(token_chunk)},
                )
                continue

            invalid_tokens.extend(self._collect_invalid_tokens(token_chunk, response))

        if invalid_tokens:
            await self.device_repository.deactivate_tokens(invalid_tokens)
            logger.info(
                "Deactivated unregistered FCM tokens",
                extra={"user_id": notification.user_id, "count": len(invalid_tokens)},
            )

    def _build_multicast(
        self, tokens: Sequence[str], notification: Notification
    ) -> messaging.MulticastMessage:
        data = {str(key): str(value) for key, value in notification.payload.items()}
        return messaging.MulticastMessage(
            tokens=list(tokens),
            notification=messaging.Notification(
                title=notification.title,
                body=notification.message or None,
            ),
            data=data,
        )

    @staticmethod
    def _collect_invalid_tokens(
        tokens: Sequence[str], response: messaging.BatchResponse
    ) -> list[str]:
        invalid: list[str] = []
        for token, resp in zip(tokens, response.responses, strict=False):
            if resp.success:
                continue

            exception = resp.exception
            if _is_unregistered(exception):
                invalid.append(token)
            else:
                logger.warning(
                    "FCM token delivery failed",
                    extra={"error": type(exception).__name__ if exception else "unknown"},
                )
        return invalid


def _is_unregistered(exception: Exception | None) -> bool:
    if exception is None:
        return False
    if isinstance(exception, messaging.UnregisteredError):
        return True
    return isinstance(exception, messaging.SenderIdMismatchError)
