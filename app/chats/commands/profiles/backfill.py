import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.repositories.user_profile import ChatUserProfileRepository
from app.core.commands import BaseCommand, BaseCommandHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillChatProfilesCommand(BaseCommand):
    batch_size: int = 500


@dataclass(frozen=True)
class BackfillChatProfilesCommandHandler(
    BaseCommandHandler[BackfillChatProfilesCommand, dict[str, int]]
):
    session: AsyncSession
    profile_repository: ChatUserProfileRepository

    async def handle(self, command: BackfillChatProfilesCommand) -> dict[str, int]:
        updated = 0
        skipped = 0
        last_id = 0

        while True:
            result = await self.session.execute(
                text(
                    """
                    SELECT id, username, display_name, avatar_s3_key, updated_at
                    FROM profiles
                    WHERE id > :last_id AND deleted_at IS NULL
                    ORDER BY id
                    LIMIT :limit
                    """
                ),
                {"last_id": last_id, "limit": command.batch_size},
            )
            rows = result.mappings().all()
            if not rows:
                break

            for row in rows:
                applied = await self.profile_repository.upsert(
                    user_id=int(row["id"]),
                    username=row["username"],
                    display_name=row["display_name"],
                    avatar_s3_key=row["avatar_s3_key"],
                    source_updated_at=row["updated_at"],
                    event_id=None,
                )
                if applied:
                    updated += 1
                else:
                    skipped += 1

            last_id = int(rows[-1]["id"])
            await self.session.commit()

        stats = {"updated": updated, "skipped": skipped}
        logger.info("Chat profile projection backfill finished", extra=stats)
        return stats
