from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.chats.models.profile import ChatUserProfile
from app.core.db.repository import CacheRepository, IRepository
from app.core.utils import now_utc


@dataclass
class ChatUserProfileRepository(IRepository[ChatUserProfile], CacheRepository):

    async def get_by_ids(self, user_ids: list[int]) -> list[ChatUserProfile]:
        if not user_ids:
            return []

        stmt = select(ChatUserProfile).where(ChatUserProfile.user_id.in_(list(user_ids)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, user_id: int) -> ChatUserProfile | None:
        stmt = select(ChatUserProfile).where(ChatUserProfile.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar()

    async def upsert(
        self,
        user_id: int,
        username: str | None,
        display_name: str | None,
        avatar_s3_key: str | None,
        source_updated_at: datetime,
        event_id: UUID | None = None,
    ) -> bool:

        now = now_utc()
        stmt = (
            insert(ChatUserProfile)
            .values(
                user_id=user_id,
                username=username,
                display_name=display_name,
                avatar_s3_key=avatar_s3_key,
                last_event_id=event_id,
                source_updated_at=source_updated_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[ChatUserProfile.user_id],
                set_={
                    "username": username,
                    "display_name": display_name,
                    "avatar_s3_key": avatar_s3_key,
                    "last_event_id": event_id,
                    "source_updated_at": source_updated_at,
                    "updated_at": now,
                },
                where=(
                    or_(
                        ChatUserProfile.source_updated_at.is_(None),
                        ChatUserProfile.source_updated_at < source_updated_at,
                    )
                ),
            )
            .returning(ChatUserProfile.user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None
