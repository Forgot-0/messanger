from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.core.api.builder import create_response
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData
from app.core.services.idempotency import IdempotencyStore
from app.core.services.queues.service import QueueService
from app.profiles.commands.contacts.add import AddContactCommand
from app.profiles.commands.contacts.block import BlockUserCommand
from app.profiles.commands.contacts.import_batch import ImportContactsCommand
from app.profiles.commands.contacts.remove import RemoveContactCommand
from app.profiles.commands.contacts.unblock import UnblockUserCommand
from app.profiles.commands.contacts.update import UpdateContactCommand
from app.profiles.config import profile_config
from app.profiles.dtos.contacts import (
    BlockedListDTO,
    ContactListDTO,
    ContactSearchDTO,
    ImportContactsResultDTO,
    ImportStatus,
    UserContactDTO,
)
from app.profiles.exceptions import (
    ContactBlockedError,
    ContactLimitExceededError,
    IdentifierQuotaExceededError,
    NotFoundContactError,
    NotFoundContactTargetError,
    SelfContactError,
)
from app.profiles.keys import ProfileIdempotencyScope
from app.profiles.queries.contacts.get_blocked import GetBlockedUsersQuery
from app.profiles.queries.contacts.get_list import GetContactsQuery
from app.profiles.queries.contacts.search import SearchContactsQuery
from app.profiles.schemas.contacts.requests import (
    AddContactRequest,
    GetBlockedRequest,
    GetContactsRequest,
    ImportContactsRequest,
    SearchContactsRequest,
    UpdateContactRequest,
)
from app.profiles.tasks import ContactsImportTask

router = APIRouter(route_class=DishkaRoute)

@router.get(
    "/",
    status_code=status.HTTP_200_OK,
)
async def get_contacts(
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    params: Annotated[GetContactsRequest, Query()],
) -> ContactListDTO:
    return await mediator.handle_query(
        GetContactsQuery(
            owner_id=int(user_jwt_data.id),
            limit=params.limit,
            after_contact_id=params.after_contact_id,
            updated_after=params.updated_after,
            user_jwt_data=user_jwt_data,
        )
    )


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: create_response(SelfContactError()),
        404: create_response(NotFoundContactTargetError(user_id=123, username=None)),
        409: create_response([
            ContactBlockedError(user_id=123),
            ContactLimitExceededError(limit=profile_config.MAX_CONTACTS_PER_USER),
        ]),
    },
)
async def add_contact(
    payload: AddContactRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> UserContactDTO:
    return await mediator.handle_command(
        AddContactCommand(
            owner_id=int(user_jwt_data.id),
            user_id=payload.user_id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
            user_jwt_data=user_jwt_data,
        )
    )


@router.post(
    "/import/",
    status_code=status.HTTP_200_OK,
    dependencies=[
        Depends(
            ConfigurableRateLimiter(
                times=profile_config.CONTACTS_IMPORT_RATE_TIMES,
                seconds=profile_config.CONTACTS_IMPORT_RATE_SECONDS,
            )
        )
    ],
    responses={
        409: create_response(ContactLimitExceededError(limit=profile_config.MAX_CONTACTS_PER_USER)),
        429: create_response(
            IdentifierQuotaExceededError(limit=profile_config.CONTACTS_NEW_IDENTIFIERS_PER_DAY)
        ),
    },
)
async def import_contacts(
    payload: ImportContactsRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    idempotency: FromDishka[IdempotencyStore],
    queue_service: FromDishka[QueueService],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportContactsResultDTO:
    owner_id = int(user_jwt_data.id)
    entries = payload.to_entries()

    if len(entries) > profile_config.CONTACTS_IMPORT_SYNC_THRESHOLD:
        response.status_code = status.HTTP_202_ACCEPTED
        return await idempotency.run(
            scope=ProfileIdempotencyScope.IMPORT_CONTACTS,
            key=idempotency_key,
            owner=(owner_id, "async"),
            model=ImportContactsResultDTO,
            operation=lambda: _queue_import(queue_service, owner_id, payload),
        )

    return await idempotency.run(
        scope=ProfileIdempotencyScope.IMPORT_CONTACTS,
        key=idempotency_key,
        owner=(owner_id, "sync"),
        model=ImportContactsResultDTO,
        operation=lambda: mediator.handle_command(
            ImportContactsCommand(
                owner_id=owner_id,
                entries=entries,
                user_jwt_data=user_jwt_data,
            )
        ),
    )


async def _queue_import(
    queue_service: QueueService, owner_id: int, payload: ImportContactsRequest
) -> ImportContactsResultDTO:
    await queue_service.push(
        ContactsImportTask,
        {
            "owner_id": owner_id,
            "entries": [item.model_dump() for item in payload.contacts],
        },
    )
    return ImportContactsResultDTO(status=ImportStatus.QUEUED, accepted=len(payload.contacts))


@router.get(
    "/search/",
    status_code=status.HTTP_200_OK,
)
async def search_contacts(
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    params: Annotated[SearchContactsRequest, Query()],
) -> ContactSearchDTO:
    return await mediator.handle_query(
        SearchContactsQuery(
            owner_id=int(user_jwt_data.id),
            query=params.query,
            limit=params.limit,
            user_jwt_data=user_jwt_data,
        )
    )


@router.get(
    "/blocked/",
    status_code=status.HTTP_200_OK,
)
async def get_blocked_users(
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    params: Annotated[GetBlockedRequest, Query()],
) -> BlockedListDTO:
    return await mediator.handle_query(
        GetBlockedUsersQuery(
            owner_id=int(user_jwt_data.id),
            limit=params.limit,
            after_target_id=params.after_target_id,
            user_jwt_data=user_jwt_data,
        )
    )


@router.patch(
    "/{user_id}/",
    status_code=status.HTTP_200_OK,
    responses={
        404: create_response(NotFoundContactError(contact_id=123)),
    },
)
async def update_contact(
    user_id: int,
    payload: UpdateContactRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> UserContactDTO:
    return await mediator.handle_command(
        UpdateContactCommand(
            owner_id=int(user_jwt_data.id),
            contact_id=user_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            is_favorite=payload.is_favorite,
            user_jwt_data=user_jwt_data,
        )
    )


@router.delete(
    "/{user_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: create_response(NotFoundContactError(contact_id=123)),
    },
)
async def remove_contact(
    user_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        RemoveContactCommand(
            owner_id=int(user_jwt_data.id),
            contact_id=user_id,
            user_jwt_data=user_jwt_data,
        )
    )


@router.post(
    "/{user_id}/block/",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: create_response(SelfContactError()),
    },
)
async def block_user(
    user_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        BlockUserCommand(
            owner_id=int(user_jwt_data.id),
            target_id=user_id,
            user_jwt_data=user_jwt_data,
        )
    )


@router.delete(
    "/{user_id}/block/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unblock_user(
    user_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        UnblockUserCommand(
            owner_id=int(user_jwt_data.id),
            target_id=user_id,
            user_jwt_data=user_jwt_data,
        )
    )
