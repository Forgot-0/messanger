from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ApplicationError


@dataclass(kw_only=True)
class NotFoundNotificationError(ApplicationError):
    notification_id: int

    status: int = 404
    code: str = "NOT_FOUND_NOTIFICATION"

    @property
    def message(self) -> str:
        return "Notification not found"

    @property
    def detail(self) -> dict[str, Any] | list[dict[str, Any]]:
        return {"notification_id": self.notification_id}


@dataclass(kw_only=True)
class NotificationAccessDeniedError(ApplicationError):
    notification_id: int

    status: int = 403
    code: str = "NOTIFICATION_ACCESS_DENIED"

    @property
    def message(self) -> str:
        return "Access to notification denied"

    @property
    def detail(self) -> dict[str, Any] | list[dict[str, Any]]:
        return {"notification_id": self.notification_id}


@dataclass(kw_only=True)
class AlreadyExistDeviceTokennError(ApplicationError):
    status: int = 400
    code: str = "ALREADY_EXIST_DEVICE_TOKEN"

    @property
    def message(self) -> str:
        return "Device token already exist"
