from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.notifications.models.notification import NotificationType


class NotificationDTO(BaseModel):
    id: int
    user_id: int
    type: NotificationType
    title: str
    message: str | None
    payload: dict
    is_read: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)



class NotificationUnreadCountDTO(BaseModel):
    unread_count: int
