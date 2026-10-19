from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query, status

from app.core.api.builder import create_response
from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.api.schemas import ORJSONResponse
from app.core.db.repository import PageResult
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData, OptionalCurrentUserJWTData
from app.profiles.commands.profiles.add_link import AddLinkToProfileCommand
from app.profiles.commands.profiles.delete_photo import DeleteProfilePhotoCommand
from app.profiles.commands.profiles.get_or_create import GetOrCreateProfileCommand
from app.profiles.commands.profiles.remove_link import RemoveLinkFromProfileCommand
from app.profiles.commands.profiles.set_main_photo import SetMainProfilePhotoCommand
from app.profiles.commands.profiles.update import UpdateProfileCommand
from app.profiles.commands.profiles.update_avatar import UpdateProfileAvatarCommand
from app.profiles.commands.profiles.upload_avatar import UloadProfileAvatarCommand
from app.profiles.config import profile_config
from app.profiles.dtos.profiles import AvatarPresign, ProfileDTO, ProfilePhotoDTO
from app.profiles.exceptions import (
    NotFoundProfileError,
    NotFoundProfilePhotoError,
    NotFoundUsernameProfileError,
    ProfilePhotosLimitError,
)
from app.profiles.queries.profiles.get_by_id import GetProfileByIdQuery
from app.profiles.queries.profiles.get_by_username import GetProfileByUsernameQuery
from app.profiles.queries.profiles.get_list import GetProfilesQuery
from app.profiles.queries.profiles.get_photos import GetProfilePhotosQuery
from app.profiles.schemas.profiles.requests import (
    AddProfileLinkRequest,
    AvatarPreSignUrlRequest,
    AvatarUploadCompleteRequest,
    GetProfilePhotosRequest,
    GetProfilesRequest,
    ProfileUpdateRequest,
)

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    dependencies=[
        Depends(
            ConfigurableRateLimiter(
                times=profile_config.PROFILE_SEARCH_RATE_TIMES,
                seconds=profile_config.PROFILE_SEARCH_RATE_SECONDS,
            )
        )
    ],
)
async def get_profiles(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
    params: Annotated[GetProfilesRequest, Query(...)]
) -> PageResult[ProfileDTO]:
    return await mediator.handle_query(
        GetProfilesQuery(
            params.to_profile_filter(),
            viewer_id=int(user_jwt_data.id),
            query=params.q,
        )
    )

@router.get(
    "/my/",
    status_code=status.HTTP_200_OK
)
async def get_or_create(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> ProfileDTO:
    return await mediator.handle_command(
        GetOrCreateProfileCommand(
            user_id=int(user_jwt_data.id), username=user_jwt_data.username
        )
    )

@router.delete(
    "/avatar/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the current profile photo; the previous one becomes current",
    responses={
        404: create_response(NotFoundProfileError(profile_id=123))
    },
    dependencies=[
        Depends(
            ConfigurableRateLimiter(
                times=profile_config.PROFILE_PHOTO_WRITE_RATE_TIMES,
                seconds=profile_config.PROFILE_PHOTO_WRITE_RATE_SECONDS,
            )
        )
    ],
)
async def delete_avatar(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> None:
    await mediator.handle_command(DeleteProfilePhotoCommand(user_jwt_data=user_jwt_data))

@router.put(
    "/photos/{photo_id}/main/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Make an older profile photo the current one",
    responses={
        404: create_response(
            [NotFoundProfileError(profile_id=123), NotFoundProfilePhotoError(photo_id="uuid")]
        )
    },
    dependencies=[
        Depends(
            ConfigurableRateLimiter(
                times=profile_config.PROFILE_PHOTO_WRITE_RATE_TIMES,
                seconds=profile_config.PROFILE_PHOTO_WRITE_RATE_SECONDS,
            )
        )
    ],
)
async def set_main_profile_photo(
    photo_id: UUID,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> None:
    await mediator.handle_command(
        SetMainProfilePhotoCommand(photo_id=photo_id, user_jwt_data=user_jwt_data)
    )

@router.delete(
    "/photos/{photo_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photo from own profile history",
    responses={
        404: create_response(
            [NotFoundProfileError(profile_id=123), NotFoundProfilePhotoError(photo_id="uuid")]
        )
    },
    dependencies=[
        Depends(
            ConfigurableRateLimiter(
                times=profile_config.PROFILE_PHOTO_WRITE_RATE_TIMES,
                seconds=profile_config.PROFILE_PHOTO_WRITE_RATE_SECONDS,
            )
        )
    ],
)
async def delete_profile_photo(
    photo_id: UUID,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> None:
    await mediator.handle_command(
        DeleteProfilePhotoCommand(user_jwt_data=user_jwt_data, photo_id=photo_id)
    )

@router.put(
    "/{profile_id}/",
    status_code=status.HTTP_200_OK,
    responses={
        404: create_response(NotFoundProfileError(profile_id=123))
    }
)
async def update_profile(
    profile_id: int,
    profile_request: ProfileUpdateRequest,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData
) -> None:
    await mediator.handle_command(
        UpdateProfileCommand(
            profile_id=profile_id,
            specialization=profile_request.specialization,
            display_name=profile_request.display_name,
            bio=profile_request.bio,
            skills=profile_request.skills,
            date_birthday=profile_request.date_birthday,
            user_jwt_data=user_jwt_data
        )
    )

@router.get(
    "/u/{username}/",
    status_code=status.HTTP_200_OK,
    responses={
        404: create_response(NotFoundUsernameProfileError(username="test"))
    }
)
async def get_profile_by_username(
    username: str,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: OptionalCurrentUserJWTData,
) -> ProfileDTO:
    return await mediator.handle_query(
        GetProfileByUsernameQuery(
            username=username,
            viewer_id=int(user_jwt_data.id) if user_jwt_data else None,
        )
    )

@router.get(
    "/{profile_id}/",
    status_code=status.HTTP_200_OK,
    responses={
        404: create_response(NotFoundProfileError(profile_id=123))
    },
)
async def get_profile(
    profile_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> ProfileDTO:
    return await mediator.handle_query(GetProfileByIdQuery(profile_id, user_jwt_data=user_jwt_data))

@router.get(
    "/{profile_id}/photos/",
    status_code=status.HTTP_200_OK,
    summary="Profile photo history, the current photo first",
    responses={
        404: create_response(NotFoundProfileError(profile_id=123))
    },
)
async def get_profile_photos(
    profile_id: int,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
    params: Annotated[GetProfilePhotosRequest, Query()],
) -> PageResult[ProfilePhotoDTO]:
    return await mediator.handle_query(
        GetProfilePhotosQuery(
            profile_id=profile_id,
            photo_filter=params.to_photo_filter(profile_id),
            user_jwt_data=user_jwt_data,
        )
    )

@router.post(
    "/avatar/upload_complete/",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def upload_avatar_complete(
    profile_request: AvatarUploadCompleteRequest,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData
) -> ORJSONResponse:
    await mediator.handle_command(
        UpdateProfileAvatarCommand(
            file_key=profile_request.file_key,
            user_jwt_data=user_jwt_data
        )
    )
    return ORJSONResponse("OK")

@router.post(
    "/avatar/presign/",
    status_code=status.HTTP_200_OK,
    responses={
        409: create_response(ProfilePhotosLimitError(limit=profile_config.MAX_PROFILE_PHOTOS))
    },
    dependencies=[Depends(ConfigurableRateLimiter(times=4, seconds=5*60))]
)
async def get_avatar_presign_url(
    profile_request: AvatarPreSignUrlRequest,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> AvatarPresign:
    return await mediator.handle_command(
        UloadProfileAvatarCommand(
            user_id=int(user_jwt_data.id),
            file_name=profile_request.filename,
            user_jwt_data=user_jwt_data
        )
    )


@router.post(
    "/{profile_id}/links/",
    status_code=status.HTTP_200_OK,
)
async def add_link_profile(
    profile_id: int,
    profile_request: AddProfileLinkRequest,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData
) -> None:
    await mediator.handle_command(
        AddLinkToProfileCommand(
            profile_id=profile_id,
            provider=profile_request.provider,
            contact=profile_request.contact,
            user_jwt_data=user_jwt_data
        )
    )

@router.delete(
    "/{profile_id}/links/{provider}/",
    status_code=status.HTTP_200_OK,
)
async def remove_link_profile(
    profile_id: int,
    provider: str,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData
) -> None:
    await mediator.handle_command(
        RemoveLinkFromProfileCommand(
            profile_id=profile_id,
            provider=provider,
            user_jwt_data=user_jwt_data
        )
    )

