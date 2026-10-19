from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query, status

from app.chats.commands.join_requests.approve import ApproveJoinRequestCommand
from app.chats.commands.join_requests.cancel import CancelJoinRequestCommand
from app.chats.commands.join_requests.decline import DeclineJoinRequestCommand
from app.chats.config import chat_config
from app.chats.dtos.join_requests import ListJoinRequests
from app.chats.queries.join_requests.get_list import GetJoinRequestsQuery
from app.chats.schemas.rest import GetJoinRequestsRequest
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData

router = APIRouter(route_class=DishkaRoute)

moderate_limiter = ConfigurableRateLimiter(
    times=chat_config.JOIN_REQUEST_MODERATE_RATE_LIMIT_TIMES,
    seconds=chat_config.JOIN_REQUEST_MODERATE_RATE_LIMIT_SECONDS,
)


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
)
async def list_join_requests(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    get_request: Annotated[GetJoinRequestsRequest, Query()],
) -> ListJoinRequests:
    return await mediator.handle_query(
        GetJoinRequestsQuery(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            limit=get_request.limit,
            last_requested_at=get_request.last_requested_at,
            last_user_id=get_request.last_user_id,
        )
    )


@router.delete(
    "/me/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(moderate_limiter)],
)
async def cancel_my_join_request(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        CancelJoinRequestCommand(user_jwt_data=user_jwt_data, chat_id=chat_id)
    )


@router.post(
    "/{user_id}/approve/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(moderate_limiter)],
)
async def approve_join_request(
    chat_id: UUID,
    user_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        ApproveJoinRequestCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            target_user_id=user_id,
        )
    )


@router.post(
    "/{user_id}/decline/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(moderate_limiter)],
)
async def decline_join_request(
    chat_id: UUID,
    user_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        DeclineJoinRequestCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            target_user_id=user_id,
        )
    )
