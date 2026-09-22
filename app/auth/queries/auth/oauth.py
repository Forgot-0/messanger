from dataclasses import dataclass

from app.auth.dtos.tokens import OAuthAccountDTO
from app.auth.dtos.user import AuthUserJWTData
from app.auth.repositories.oauth import OauthAccountRepository
from app.core.queries import BaseQuery, BaseQueryHandler


@dataclass(frozen=True)
class GetUserOAuthAccountsQuery(BaseQuery):
    user_jwt_data: AuthUserJWTData


@dataclass(frozen=True)
class GetUserOAuthAccountsQueryHandler(BaseQueryHandler[GetUserOAuthAccountsQuery, list[OAuthAccountDTO]]):
    oauth_repository: OauthAccountRepository

    async def handle(self, query: GetUserOAuthAccountsQuery) -> list[OAuthAccountDTO]:
        accounts = await self.oauth_repository.get_by_user_id(int(query.user_jwt_data.id))
        return [
            OAuthAccountDTO.model_validate(acc)
            for acc in accounts
        ]
