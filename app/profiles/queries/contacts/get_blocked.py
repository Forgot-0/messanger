from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.config import profile_config
from app.profiles.dtos.contacts import BlockedListDTO, BlockedUserDTO
from app.profiles.repositories.contacts import BlockedUserRepository
from app.profiles.services.contact_access import check_contact_owner


@dataclass(frozen=True)
class GetBlockedUsersQuery(BaseQuery):
    owner_id: int

    limit: int = profile_config.CONTACTS_PAGE_SIZE
    after_target_id: int | None = None

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class GetBlockedUsersQueryHandler(BaseQueryHandler[GetBlockedUsersQuery, BlockedListDTO]):
    blocked_repository: BlockedUserRepository
    rbac_manager: RBACManagerInterface

    async def handle(self, query: GetBlockedUsersQuery) -> BlockedListDTO:
        check_contact_owner(self.rbac_manager, query.owner_id, query.user_jwt_data)

        limit = min(max(query.limit, 1), profile_config.CONTACTS_MAX_PAGE_SIZE)
        rows, has_next = await self.blocked_repository.list_page(
            owner_id=query.owner_id,
            limit=limit,
            after_target_id=query.after_target_id,
        )

        blocked = [BlockedUserDTO.model_validate(row) for row in rows]

        return BlockedListDTO(
            blocked=[BlockedUserDTO.model_validate(row) for row in rows],
            has_next=has_next,
            next_target_id=blocked[-1].target_id if has_next and blocked else None,
        )
