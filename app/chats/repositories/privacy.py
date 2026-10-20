from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.chats.models.blocks import ChatUserBlock
from app.chats.models.chat_members import ChatMember
from app.chats.models.privacy import ChatUserContact, ChatUserPrivacyException
from app.chats.models.profile import ChatUserProfile
from app.core.db.repository import IRepository
from app.core.utils import now_utc
from app.privacy.utils import DEFAULT_VISIBILITY, PrivacyRule, PrivacyVisibility


@dataclass(frozen=True, slots=True)
class DirectPeerState:
    peer_id: int
    blocked: bool
    visibility: PrivacyVisibility
    exception: bool | None


@dataclass
class ChatPrivacyProjectionRepository(IRepository[ChatUserProfile]):

    async def direct_peer_state(
        self, chat_id: UUID, viewer_id: int, rule: PrivacyRule
    ) -> DirectPeerState | None:
        peer = aliased(ChatMember)
        column = getattr(ChatUserProfile, ChatUserProfile.privacy_column_name(rule))

        blocked = exists().where(
            or_(
                and_(
                    ChatUserBlock.owner_id == peer.user_id,
                    ChatUserBlock.target_id == viewer_id,
                ),
                and_(
                    ChatUserBlock.owner_id == viewer_id,
                    ChatUserBlock.target_id == peer.user_id,
                ),
            )
        )
        exception = (
            select(ChatUserPrivacyException.allow)
            .where(
                ChatUserPrivacyException.owner_id == peer.user_id,
                ChatUserPrivacyException.rule == rule.value,
                ChatUserPrivacyException.target_id == viewer_id,
            )
            .scalar_subquery()
        )

        stmt = (
            select(peer.user_id, blocked, column, exception)
            .select_from(peer)
            .outerjoin(ChatUserProfile, ChatUserProfile.user_id == peer.user_id)
            .where(peer.chat_id == chat_id, peer.user_id != viewer_id)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None

        peer_id, is_blocked, visibility, allow = row
        return DirectPeerState(
            peer_id=int(peer_id),
            blocked=bool(is_blocked),
            visibility=(
                DEFAULT_VISIBILITY
                if visibility is None
                else ChatUserProfile.parse_visibility(visibility)
            ),
            exception=None if allow is None else bool(allow),
        )

    async def visibility_map(
        self, rule: PrivacyRule, owner_ids: Collection[int]
    ) -> dict[int, PrivacyVisibility]:
        if not owner_ids:
            return {}

        column = getattr(ChatUserProfile, ChatUserProfile.privacy_column_name(rule))
        stmt = select(ChatUserProfile.user_id, column).where(
            ChatUserProfile.user_id.in_(list(owner_ids))
        )
        result = await self.session.execute(stmt)

        return {
            int(user_id): ChatUserProfile.parse_visibility(value)
            for user_id, value in result.all()
        }

    async def exceptions_for(
        self, rule: PrivacyRule, target_id: int, owner_ids: Collection[int]
    ) -> dict[int, bool]:
        if not owner_ids:
            return {}

        stmt = select(ChatUserPrivacyException.owner_id, ChatUserPrivacyException.allow).where(
            ChatUserPrivacyException.rule == rule.value,
            ChatUserPrivacyException.target_id == target_id,
            ChatUserPrivacyException.owner_id.in_(list(owner_ids)),
        )
        result = await self.session.execute(stmt)

        return {int(owner_id): bool(allow) for owner_id, allow in result.all()}

    async def contacts_of(self, contact_id: int, owner_ids: Collection[int]) -> set[int]:
        if not owner_ids:
            return set()

        stmt = select(ChatUserContact.owner_id).where(
            ChatUserContact.contact_id == contact_id,
            ChatUserContact.owner_id.in_(list(owner_ids)),
        )
        result = await self.session.execute(stmt)
        return {int(owner_id) for owner_id in result.scalars().all()}

    async def direct_peer(self, chat_id: UUID, user_id: int) -> int | None:
        stmt = (
            select(ChatMember.user_id)
            .where(ChatMember.chat_id == chat_id, ChatMember.user_id != user_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        peer_id = result.scalar()
        return int(peer_id) if peer_id is not None else None

    async def upsert_privacy(
        self,
        user_id: int,
        rules: Mapping[str, str],
        source_updated_at: datetime,
    ) -> bool:
        now = now_utc()
        columns = {
            ChatUserProfile.privacy_column_name(rule): str(
                rules.get(rule.value, DEFAULT_VISIBILITY.value)
            )[:16]
            for rule in PrivacyRule
        }

        stmt = (
            insert(ChatUserProfile)
            .values(
                user_id=user_id,
                last_event_id=None,
                privacy_source_updated_at=source_updated_at,
                created_at=now,
                updated_at=now,
                **columns,
            )
            .on_conflict_do_update(
                index_elements=[ChatUserProfile.user_id],
                set_={
                    **columns,
                    "privacy_source_updated_at": source_updated_at,
                    "updated_at": now,
                },
                where=(
                    or_(
                        ChatUserProfile.privacy_source_updated_at.is_(None),
                        ChatUserProfile.privacy_source_updated_at < source_updated_at,
                    )
                ),
            )
            .returning(ChatUserProfile.user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def replace_exceptions(
        self, owner_id: int, exceptions: Mapping[str, Mapping[str, Collection[int]]]
    ) -> None:
        await self.session.execute(
            delete(ChatUserPrivacyException).where(
                ChatUserPrivacyException.owner_id == owner_id
            )
        )

        known = {rule.value for rule in PrivacyRule}
        rows = [
            {
                "owner_id": owner_id,
                "rule": rule,
                "target_id": int(target_id),
                "allow": allow,
            }
            for rule, buckets in exceptions.items()
            if rule in known
            for bucket, allow in (("allow", True), ("deny", False))
            for target_id in buckets.get(bucket, ())
            if int(target_id) != owner_id
        ]
        if not rows:
            return

        await self.session.execute(
            insert(ChatUserPrivacyException)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    ChatUserPrivacyException.owner_id,
                    ChatUserPrivacyException.rule,
                    ChatUserPrivacyException.target_id,
                ]
            )
        )

    async def add_contact(self, owner_id: int, contact_id: int) -> bool:
        stmt = (
            insert(ChatUserContact)
            .values(owner_id=owner_id, contact_id=contact_id)
            .on_conflict_do_nothing(
                index_elements=[ChatUserContact.owner_id, ChatUserContact.contact_id]
            )
            .returning(ChatUserContact.owner_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def remove_contact(self, owner_id: int, contact_id: int) -> bool:
        stmt = (
            delete(ChatUserContact)
            .where(
                ChatUserContact.owner_id == owner_id,
                ChatUserContact.contact_id == contact_id,
            )
            .returning(ChatUserContact.owner_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None
