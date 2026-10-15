from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query, status

from app.chats.commands.pins.pin import PinMessageCommand
from app.chats.commands.pins.unpin import UnpinMessagesCommand
from app.chats.config import chat_config
from app.chats.dtos.pins import PinnedMessageDTO, PinnedMessagesDTO
from app.chats.queries.pins.get_list import GetPinnedMessagesQuery
from app.chats.schemas.rest import GetPinnedMessagesRequest
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData

router = APIRouter(route_class=DishkaRoute)

pin_write_limiter = ConfigurableRateLimiter(
    times=chat_config.PIN_RATE_LIMIT_TIMES,
    seconds=chat_config.PIN_RATE_LIMIT_SECONDS,
)


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
)
async def list_pinned_messages(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    get_request: Annotated[GetPinnedMessagesRequest, Query()],
) -> PinnedMessagesDTO:
    return await mediator.handle_query(
        GetPinnedMessagesQuery(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            limit=get_request.limit,
            before_seq=get_request.before_seq,
        )
    )


@router.delete(
    "/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(pin_write_limiter)],
)
async def unpin_all_messages(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        UnpinMessagesCommand(user_jwt_data=user_jwt_data, chat_id=chat_id)
    )


@router.put(
    "/{message_id}/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(pin_write_limiter)],
)
async def pin_message(
    chat_id: UUID,
    message_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> PinnedMessageDTO:
    return await mediator.handle_command(
        PinMessageCommand(user_jwt_data=user_jwt_data, chat_id=chat_id, message_id=message_id)
    )


@router.delete(
    "/{message_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(pin_write_limiter)],
)
async def unpin_message(
    chat_id: UUID,
    message_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        UnpinMessagesCommand(user_jwt_data=user_jwt_data, chat_id=chat_id, message_id=message_id)
    )
