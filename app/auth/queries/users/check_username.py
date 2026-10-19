from dataclasses import dataclass

from app.auth.dtos.user import AuthUserJWTData, UsernameAvailabilityDTO
from app.auth.exceptions import InvalidUsernameError
from app.auth.models.user import User
from app.auth.repositories.user import UserRepository
from app.core.queries import BaseQuery, BaseQueryHandler


@dataclass(frozen=True)
class CheckUsernameQuery(BaseQuery):
    username: str

    user_jwt_data: AuthUserJWTData


@dataclass(frozen=True)
class CheckUsernameQueryHandler(BaseQueryHandler[CheckUsernameQuery, UsernameAvailabilityDTO]):
    user_repository: UserRepository

    async def handle(self, query: CheckUsernameQuery) -> UsernameAvailabilityDTO:
        cleaned = query.username.strip().removeprefix("@")

        try:
            username = User.validate_username(query.username)
        except InvalidUsernameError as exc:
            return UsernameAvailabilityDTO.model_validate(
                {"username": cleaned, "available": False, "reason": exc.reason}
            )

        if await self.user_repository.is_username_taken(
            username, exclude_user_id=int(query.user_jwt_data.id)
        ):
            return UsernameAvailabilityDTO(username=username, available=False, reason="taken")

        return UsernameAvailabilityDTO(username=username, available=True)
