from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.chats.commands.avatars.confirm import ConfirmChatAvatarUploadCommand
from app.chats.commands.avatars.remove import RemoveChatAvatarCommand
from app.chats.commands.avatars.request_upload import RequestChatAvatarUploadCommand
from app.chats.commands.chats.create import CreateChatCommand
from app.chats.commands.chats.delete import DeleteChatCommand
from app.chats.commands.chats.join import JoinChatCommand
from app.chats.commands.chats.leave import LeaveChatCommand
from app.chats.commands.chats.set_username import SetChatUsernameCommand
from app.chats.commands.chats.transfer_ownership import TransferChatOwnershipCommand
from app.chats.commands.chats.update import UpdateChatCommand
from app.chats.commands.chats.update_state import UpdateChatStateCommand
from app.chats.commands.invites.join import JoinChatByInviteCommand
from app.chats.config import chat_config
from app.chats.dtos.avatars import ChatAvatarUploadSlotDTO
from app.chats.dtos.chats import (
    ChatDetailDTO,
    ChatDTO,
    ChatPreviewDTO,
    ChatStateDTO,
    ListChats,
    PublicChatSearchDTO,
)
from app.chats.dtos.invites import ChatInvitePreviewDTO
from app.chats.dtos.reactions import ReactionsCatalogDTO
from app.chats.dtos.search import MessageSearchDTO
from app.chats.queries.chats.get_by_username import GetChatByUsernameQuery
from app.chats.queries.chats.get_detail import GetChatDetailQuery
from app.chats.queries.chats.get_list import GetListChatUserQuery
from app.chats.queries.chats.search_public import SearchPublicChatsQuery
from app.chats.queries.invites.preview import GetInvitePreviewQuery
from app.chats.queries.messages.search import SearchMessagesQuery
from app.chats.queries.reactions.get_catalog import GetReactionsCatalogQuery
from app.chats.schemas.rest import (
    ConfirmChatAvatarUploadRequest,
    CreateChatRequest,
    GetListUserChatsRequest,
    RequestChatAvatarUploadRequest,
    SearchMessagesRequest,
    SearchPublicChatsRequest,
    SetChatUsernameRequest,
    TransferOwnershipRequest,
    UpdateChatRequest,
    UpdateChatStateRequest,
)
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/",
    status_code=status.HTTP_200_OK
)
async def list_my_chats(
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    get_request: Annotated[GetListUserChatsRequest, Query()],
) -> ListChats:
    return await mediator.handle_query(
        GetListChatUserQuery(
            user_jwt_data=user_jwt_data,
            limit=get_request.limit,
            last_chat_id=get_request.last_chat_id,
            last_activity_at=get_request.last_activity_at,
            archived=get_request.archived,
        )
    )


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def create_chat(
    payload: CreateChatRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatDTO:
    chat = await mediator.handle_command(
        CreateChatCommand(
            name=payload.name,
            description=payload.description,
            chat_type=payload.chat_type,
            member_ids=payload.member_ids,
            is_public=payload.is_public,
            admin_only=payload.admin_only,
            slow_mode_seconds=payload.slow_mode_seconds,
            permissions=payload.permissions,
            user_jwt_data=user_jwt_data,
        )
    )
    return chat

@router.get(
    "/messages/search/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.MESSAGE_SEARCH_RATE_LIMIT_TIMES,
        seconds=chat_config.MESSAGE_SEARCH_RATE_LIMIT_SECONDS,
    ))]
)
async def search_messages(
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    get_request: Annotated[SearchMessagesRequest, Query()],
) -> MessageSearchDTO:
    return await mediator.handle_query(
        SearchMessagesQuery(
            user_jwt_data=user_jwt_data,
            q=get_request.q,
            chat_id=get_request.chat_id,
            limit=get_request.limit,
            last_message_id=get_request.last_message_id,
        )
    )

@router.get(
    "/reactions/catalog/",
    status_code=status.HTTP_200_OK,
    response_model=ReactionsCatalogDTO,
)
async def get_reactions_catalog(
    request: Request,
    response: Response,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ReactionsCatalogDTO | Response:
    catalog: ReactionsCatalogDTO = await mediator.handle_query(
        GetReactionsCatalogQuery(user_jwt_data=user_jwt_data)
    )

    etag = f'"{catalog.version}"'
    cache_control = f"private, max-age={chat_config.REACTIONS_CATALOG_CACHE_TTL}"
    headers = {"ETag": etag, "Cache-Control": cache_control}

    if_none_match = request.headers.get("if-none-match")
    if (
        if_none_match and
        any(
            tag == "*" or tag.removeprefix("W/") == etag
            for tag in map(str.strip, if_none_match.split(","))
        )
    ):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    response.headers.update(headers)
    return catalog

@router.get(
    "/search/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.PUBLIC_CHAT_SEARCH_RATE_LIMIT_TIMES,
        seconds=chat_config.PUBLIC_CHAT_SEARCH_RATE_LIMIT_SECONDS,
    ))]
)
async def search_public_chats(
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    get_request: Annotated[SearchPublicChatsRequest, Query()],
) -> PublicChatSearchDTO:
    return await mediator.handle_query(
        SearchPublicChatsQuery(
            user_jwt_data=user_jwt_data,
            q=get_request.q,
            limit=get_request.limit,
        )
    )


@router.get(
    "/u/{username}/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.PUBLIC_CHAT_SEARCH_RATE_LIMIT_TIMES,
        seconds=chat_config.PUBLIC_CHAT_SEARCH_RATE_LIMIT_SECONDS,
    ))]
)
async def get_chat_by_username(
    username: str,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatPreviewDTO:
    return await mediator.handle_query(
        GetChatByUsernameQuery(user_jwt_data=user_jwt_data, username=username)
    )


@router.get(
    "/invites/{code}/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.INVITE_PREVIEW_RATE_LIMIT_TIMES,
        seconds=chat_config.INVITE_PREVIEW_RATE_LIMIT_SECONDS,
    ))]
)
async def preview_invite_link(
    code: str,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatInvitePreviewDTO:
    return await mediator.handle_query(
        GetInvitePreviewQuery(user_jwt_data=user_jwt_data, code=code)
    )


@router.post(
    "/invites/{code}/join/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.INVITE_JOIN_RATE_LIMIT_TIMES,
        seconds=chat_config.INVITE_JOIN_RATE_LIMIT_SECONDS,
    ))]
)
async def join_chat_by_invite(
    code: str,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatDTO:
    return await mediator.handle_command(
        JoinChatByInviteCommand(user_jwt_data=user_jwt_data, code=code)
    )


@router.get(
    "/{chat_id}/",
    status_code=status.HTTP_200_OK
)
async def get_chat_detail(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatDetailDTO:
    return await mediator.handle_query(GetChatDetailQuery(user_jwt_data=user_jwt_data, chat_id=chat_id))


@router.patch(
    "/{chat_id}/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def update_chat(
    chat_id: UUID,
    payload: UpdateChatRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatDTO:
    chat = await mediator.handle_command(
        UpdateChatCommand(
            chat_id=chat_id,
            name=payload.name,
            description=payload.description,
            is_public=payload.is_public,
            admin_only=payload.admin_only,
            slow_mode_seconds=payload.slow_mode_seconds,
            permissions=payload.permissions,
            reactions_mode=payload.reactions_mode,
            allowed_reactions=payload.allowed_reactions,
            user_jwt_data=user_jwt_data,
        )
    )
    return chat


@router.patch(
    "/{chat_id}/state/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(times=60, seconds=60))]
)
async def update_chat_state(
    chat_id: UUID,
    payload: UpdateChatStateRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatStateDTO:
    return await mediator.handle_command(
        UpdateChatStateCommand(
            chat_id=chat_id,
            user_jwt_data=user_jwt_data,
            provided=frozenset(payload.model_fields_set),
            pinned=payload.pinned,
            archived=payload.archived,
            notifications_muted_until=payload.notifications_muted_until,
            draft=payload.draft,
        )
    )


@router.delete(
    "/{chat_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def delete_chat(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(DeleteChatCommand(user_jwt_data=user_jwt_data, chat_id=chat_id))


@router.post(
    "/{chat_id}/join/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(times=10, seconds=5*60))]
)
async def join_public_chat(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(JoinChatCommand(user_jwt_data=user_jwt_data, chat_id=chat_id))


@router.post(
    "/{chat_id}/leave/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def leave_chat(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(LeaveChatCommand(chat_id=chat_id, user_jwt_data=user_jwt_data))


@router.put(
    "/{chat_id}/username/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.CHAT_USERNAME_RATE_LIMIT_TIMES,
        seconds=chat_config.CHAT_USERNAME_RATE_LIMIT_SECONDS,
    ))]
)
async def set_chat_username(
    chat_id: UUID,
    payload: SetChatUsernameRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatDTO:
    return await mediator.handle_command(
        SetChatUsernameCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            username=payload.username,
        )
    )


@router.delete(
    "/{chat_id}/username/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.CHAT_USERNAME_RATE_LIMIT_TIMES,
        seconds=chat_config.CHAT_USERNAME_RATE_LIMIT_SECONDS,
    ))]
)
async def delete_chat_username(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        SetChatUsernameCommand(user_jwt_data=user_jwt_data, chat_id=chat_id, username=None)
    )


@router.post(
    "/{chat_id}/transfer_ownership/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def transfer_chat_ownership(
    chat_id: UUID,
    payload: TransferOwnershipRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        TransferChatOwnershipCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            new_owner_id=payload.user_id,
        )
    )


@router.post(
    "/{chat_id}/avatar/upload-requests/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.CHAT_AVATAR_RATE_LIMIT_TIMES,
        seconds=chat_config.CHAT_AVATAR_RATE_LIMIT_SECONDS,
    ))]
)
async def request_chat_avatar_upload(
    chat_id: UUID,
    payload: RequestChatAvatarUploadRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ChatAvatarUploadSlotDTO:
    return await mediator.handle_command(
        RequestChatAvatarUploadCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            mime_type=payload.mime_type,
            file_size=payload.file_size,
        )
    )


@router.post(
    "/{chat_id}/avatar/upload-requests/confirm/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.CHAT_AVATAR_RATE_LIMIT_TIMES,
        seconds=chat_config.CHAT_AVATAR_RATE_LIMIT_SECONDS,
    ))]
)
async def confirm_chat_avatar_upload(
    chat_id: UUID,
    payload: ConfirmChatAvatarUploadRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        ConfirmChatAvatarUploadCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            upload_token=payload.upload_token,
        )
    )


@router.delete(
    "/{chat_id}/avatar/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(ConfigurableRateLimiter(
        times=chat_config.CHAT_AVATAR_RATE_LIMIT_TIMES,
        seconds=chat_config.CHAT_AVATAR_RATE_LIMIT_SECONDS,
    ))]
)
async def remove_chat_avatar(
    chat_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        RemoveChatAvatarCommand(user_jwt_data=user_jwt_data, chat_id=chat_id)
    )
