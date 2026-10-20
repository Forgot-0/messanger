from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db.repository import IRepository
from app.privacy.utils import PrivacyRule, PrivacyVisibility
from app.profiles.models.privacy import ProfilePrivacy, ProfilePrivacyException


@dataclass
class ProfilePrivacyRepository(IRepository[ProfilePrivacy]):

    async def get(self, user_id: int) -> ProfilePrivacy | None:
        stmt = select(ProfilePrivacy).where(ProfilePrivacy.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_or_create(self, user_id: int) -> ProfilePrivacy:
        privacy = await self.get(user_id)
        if privacy is not None:
            return privacy

        await self.session.execute(
            insert(ProfilePrivacy)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=[ProfilePrivacy.user_id])
        )

        privacy = await self.get(user_id)
        if privacy is None:
            raise RuntimeError(f"Privacy row for {user_id} is missing right after insert")

        return privacy

    async def visibility_map(
        self, rule: PrivacyRule, owner_ids: Collection[int]
    ) -> dict[int, PrivacyVisibility]:
        if not owner_ids:
            return {}

        column = getattr(ProfilePrivacy, rule.value)
        stmt = select(ProfilePrivacy.user_id, column).where(
            ProfilePrivacy.user_id.in_(list(owner_ids))
        )
        result = await self.session.execute(stmt)

        return {int(user_id): PrivacyVisibility(value) for user_id, value in result.all()}

    async def exceptions_for(
        self, rule: PrivacyRule, target_id: int, owner_ids: Collection[int]
    ) -> dict[int, bool]:
        if not owner_ids:
            return {}

        stmt = select(ProfilePrivacyException.owner_id, ProfilePrivacyException.allow).where(
            ProfilePrivacyException.rule == rule,
            ProfilePrivacyException.target_id == target_id,
            ProfilePrivacyException.owner_id.in_(list(owner_ids)),
        )
        result = await self.session.execute(stmt)

        return {int(owner_id): bool(allow) for owner_id, allow in result.all()}
