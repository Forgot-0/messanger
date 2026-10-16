from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.profiles.dtos.privacy import PrivacySettingsDTO
from app.profiles.repositories.privacy import ProfilePrivacyRepository


@dataclass(frozen=True)
class GetPrivacySettingsQuery(BaseQuery):
    user_id: int


@dataclass(frozen=True)
class GetPrivacySettingsQueryHandler(
    BaseQueryHandler[GetPrivacySettingsQuery, PrivacySettingsDTO]
):
    privacy_repository: ProfilePrivacyRepository

    async def handle(self, query: GetPrivacySettingsQuery) -> PrivacySettingsDTO:
        privacy = await self.privacy_repository.get(query.user_id)
        if privacy is None:
            return PrivacySettingsDTO.default()

        return PrivacySettingsDTO(
            rules=privacy.rules_snapshot(),  # type: ignore[arg-type]
            exceptions=privacy.exceptions_snapshot(),  # type: ignore[arg-type]
        )
