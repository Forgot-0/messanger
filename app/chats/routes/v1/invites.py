from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query, status

from app.chats.commands.invites.create import CreateInviteLinkCommand
from app.chats.commands.invites.revoke import RevokeInviteLinkCommand
from app.chats.config import chat_config
from app.chats.dtos.invites import ChatInviteLinkDTO, ListInviteLinks
from app.chats.queries.invites.get_list import GetInviteLinksQuery
from app.chats.schemas.rest import CreateInviteLinkRequest, GetInviteLinksRequest
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData

router = APIRouter(route_class=DishkaRoute)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.INVITE_LINK_CREATE_RATE_LIMIT_TIMES,
        seconds=chat_config.INVITE_LINK_CREATE_RATE_LIMIT_SECONDS,
    ))]
)
async def create_invite_link(
    chat_id: UUID,
    payload: CreateInviteLinkRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatInviteLinkDTO:
    return await mediator.handle_command(
        CreateInviteLinkCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            name=payload.name,
            expires_at=payload.expires_at,
            usage_limit=payload.usage_limit,
            creates_join_request=payload.creates_join_request,
        )
    )


@router.get(
    "/",
    status_code=status.HTTP_200_OK
)
async def list_invite_links(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    get_request: Annotated[GetInviteLinksRequest, Query()],
) -> ListInviteLinks:
    return await mediator.handle_query(
        GetInviteLinksQuery(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            limit=get_request.limit,
            last_invite_id=get_request.last_invite_id,
        )
    )


@router.delete(
    "/{invite_id}/",
    status_code=status.HTTP_200_OK
)
async def revoke_invite_link(
    chat_id: UUID,
    invite_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatInviteLinkDTO:
    return await mediator.handle_command(
        RevokeInviteLinkCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            invite_id=invite_id,
        )
    )
