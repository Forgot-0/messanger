from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, status

from app.chats.commands.calls.join import JoinCallCommand
from app.chats.commands.calls.mute import MuteParticipantCommand
from app.chats.dtos.livekit import JoinTokenDTO
from app.chats.schemas.rest import MuteParticipantRequest
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData

router = APIRouter(route_class=DishkaRoute)


@router.post(
    "/join/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(times=10, seconds=5*60))],
)
async def join_call(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> JoinTokenDTO:
    token_dto = await mediator.handle_command(JoinCallCommand(user_jwt_data=user_jwt_data, chat_id=chat_id))
    return token_dto


@router.post(
    "/participants/{user_id}/mute/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def mute_participant(
    chat_id: UUID,
    user_id: int,
    payload: MuteParticipantRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        MuteParticipantCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            target_user_id=user_id,
            muted=payload.muted,
        )
    )
