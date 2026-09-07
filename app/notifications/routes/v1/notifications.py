from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from app.core.db.repository import PageResult
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData
from app.notifications.commands.notifications.mark_all_read import MarkAllNotificationsAsReadCommand
from app.notifications.commands.notifications.mark_read import MarkNotificationAsReadCommand
from app.notifications.dtos.notifications import NotificationDTO, NotificationUnreadCountDTO
from app.notifications.queries.notifications.get_list import GetNotificationsQuery
from app.notifications.queries.notifications.get_unread_count import GetUnreadNotificationsCountQuery
from app.notifications.schemas.notifications.requests import GetNotificationListRequest, MarkNotificationAsReadRequest

router = APIRouter(route_class=DishkaRoute)


@router.get("/", status_code=status.HTTP_200_OK)
async def get_notifications(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
    params: Annotated[GetNotificationListRequest, Query()],
) -> PageResult[NotificationDTO]:
    return await mediator.handle_query(
        GetNotificationsQuery(
            notification_filter=params.to_notifications_filter(int(user_jwt_data.id))
        )
    )

@router.get("/unread_count/", status_code=status.HTTP_200_OK)
async def get_unread_notifications_count(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> NotificationUnreadCountDTO:
    return await mediator.handle_query(GetUnreadNotificationsCountQuery(user_id=int(user_jwt_data.id)))

@router.patch("/{notification_id}/read/", status_code=status.HTTP_200_OK)
async def mark_notification_as_read(
    notification_id: int,
    payload: MarkNotificationAsReadRequest,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> None:
    await mediator.handle_command(
        MarkNotificationAsReadCommand(
            notification_id=notification_id,
            is_read=payload.is_read,
            user_jwt_data=user_jwt_data
        )
    )

@router.patch("/read_all/", status_code=status.HTTP_200_OK)
async def mark_all_notifications_as_read(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> None:
    await mediator.handle_command(
        MarkAllNotificationsAsReadCommand(user_jwt_data=user_jwt_data)
    )
