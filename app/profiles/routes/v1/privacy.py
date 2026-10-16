from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, status

from app.core.api.rate_limiter import ConfigurableRateLimiter
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData
from app.profiles.commands.privacy.update import (
    PrivacyExceptionsUpdate,
    UpdatePrivacySettingsCommand,
)
from app.profiles.config import profile_config
from app.profiles.dtos.privacy import PrivacySettingsDTO
from app.profiles.queries.privacy.get import GetPrivacySettingsQuery
from app.profiles.schemas.privacy.requests import PrivacySettingsUpdateRequest

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
)
async def get_privacy_settings(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> PrivacySettingsDTO:
    return await mediator.handle_query(
        GetPrivacySettingsQuery(user_id=int(user_jwt_data.id))
    )


@router.put(
    "/",
    status_code=status.HTTP_200_OK,
    dependencies=[
        Depends(
            ConfigurableRateLimiter(
                times=profile_config.PRIVACY_UPDATE_RATE_TIMES,
                seconds=profile_config.PRIVACY_UPDATE_RATE_SECONDS,
            )
        )
    ],
)
async def update_privacy_settings(
    privacy_request: PrivacySettingsUpdateRequest,
    mediator: FromDishka[BaseMediator],
    user_jwt_data: CurrentUserJWTData,
) -> PrivacySettingsDTO:
    return await mediator.handle_command(
        UpdatePrivacySettingsCommand(
            user_id=int(user_jwt_data.id),
            rules=privacy_request.rules,
            exceptions={
                rule: PrivacyExceptionsUpdate(allow=item.allow, deny=item.deny)
                for rule, item in privacy_request.exceptions.items()
            },
        )
    )
