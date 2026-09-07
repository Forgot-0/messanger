from pydantic import BaseModel, Field

from app.core.api.filter_mapper import FilterMapper
from app.core.filters.pagination import Pagination
from app.notifications.filters.notifications import NotificationFilter


class GetNotificationListRequest(BaseModel):
    is_read: bool | None = None

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    sort: str | None = Field(default="created_at:desc")

    def to_notifications_filter(self, user_id: int) -> NotificationFilter:
        notifications_filter = NotificationFilter(
            user_id=user_id,
            is_read=self.is_read,
        )

        pagination = Pagination(page=self.page, page_size=self.page_size)
        notifications_filter.set_pagination(pagination)

        sort_fields = FilterMapper.parse_sort_string(self.sort)
        for sort_field in sort_fields:
            notifications_filter.add_sort(sort_field.field, sort_field.direction)

        return notifications_filter


class MarkNotificationAsReadRequest(BaseModel):
    is_read: bool = True
