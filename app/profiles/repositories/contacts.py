from dataclasses import dataclass
from datetime import datetime
from typing import Any

import orjson
from sqlalchemy import and_, delete, func, literal_column, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.dml import ReturningInsert

from app.core.db.repository import CacheRepository, IRepository
from app.core.utils import now_utc
from app.profiles.config import profile_config
from app.profiles.keys import ContactKeys
from app.profiles.models.contacts import (
    BlockedUser,
    ContactSource,
    IdentifierKind,
    PendingContact,
    UserContact,
    UserIdentifier,
    validate_contact_name,
)
from app.profiles.models.profile import Profile


@dataclass(frozen=True, slots=True)
class ContactUpsert:
    contact_id: int
    source: ContactSource
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True, slots=True)
class PendingUpsert:
    identifier_hash: bytes
    first_name: str | None = None
    last_name: str | None = None


@dataclass
class ContactRepository(IRepository[UserContact]):

    async def get(
        self, owner_id: int, contact_id: int, with_profile: bool = False
    ) -> UserContact | None:
        stmt = select(UserContact).where(
            UserContact.owner_id == owner_id, UserContact.contact_id == contact_id
        )

        if with_profile:
            stmt = stmt.options(selectinload(UserContact.profile))

        result = await self.session.execute(stmt)
        return result.scalar()

    async def count(self, owner_id: int) -> int:
        stmt = select(func.count()).select_from(UserContact).where(UserContact.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_page(
        self,
        owner_id: int,
        limit: int,
        after_contact_id: int | None = None,
        updated_after: datetime | None = None,
    ) -> tuple[list[UserContact], bool]:
        stmt = (
            select(UserContact)
            .options(selectinload(UserContact.profile))
            .where(UserContact.owner_id == owner_id)
            .order_by(UserContact.contact_id)
            .limit(limit + 1)
        )

        if after_contact_id is not None:
            stmt = stmt.where(UserContact.contact_id > after_contact_id)

        if updated_after is not None:
            stmt = stmt.where(UserContact.updated_at >= updated_after)

        result = await self.session.execute(stmt)
        contacts = list(result.scalars().all())

        return contacts[:limit], len(contacts) > limit

    async def get_many(self, owner_id: int, contact_ids: list[int]) -> list[UserContact]:
        if not contact_ids:
            return []

        stmt = (
            select(UserContact)
            .options(selectinload(UserContact.profile))
            .where(
                UserContact.owner_id == owner_id,
                UserContact.contact_id.in_(contact_ids),
            )
            .order_by(UserContact.contact_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def max_updated_at(self, owner_id: int) -> datetime | None:
        stmt = select(func.max(UserContact.updated_at)).where(UserContact.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return result.scalar()

    async def upsert_many(self, owner_id: int, entries: list[ContactUpsert]) -> set[int]:
        if not entries:
            return set()

        now = now_utc()
        values = [
            {
                "owner_id": owner_id,
                "contact_id": entry.contact_id,
                "first_name": validate_contact_name(entry.first_name),
                "last_name": validate_contact_name(entry.last_name),
                "source": int(entry.source),
                "is_mutual": False,
                "is_favorite": False,
                "created_at": now,
                "updated_at": now,
            }
            for entry in entries
        ]

        insert_stmt = insert(UserContact).values(values)
        upsert_stmt: ReturningInsert[Any] = insert_stmt.on_conflict_do_update(
            index_elements=[UserContact.owner_id, UserContact.contact_id],
            set_={
                "first_name": func.coalesce(insert_stmt.excluded.first_name, UserContact.first_name),
                "last_name": func.coalesce(insert_stmt.excluded.last_name, UserContact.last_name),
                "updated_at": now,
            },
        ).returning(UserContact.contact_id, literal_column("xmax = 0").label("inserted"))

        result = await self.session.execute(upsert_stmt)
        return {row.contact_id for row in result.all() if row.inserted}

    async def upsert_many_pairs(self, entries: list[tuple[int, ContactUpsert]]) -> set[tuple[int, int]]:
        if not entries:
            return set()

        now = now_utc()
        values = [
            {
                "owner_id": owner_id,
                "contact_id": entry.contact_id,
                "first_name": validate_contact_name(entry.first_name),
                "last_name": validate_contact_name(entry.last_name),
                "source": int(entry.source),
                "is_mutual": False,
                "is_favorite": False,
                "created_at": now,
                "updated_at": now,
            }
            for owner_id, entry in entries
        ]

        insert_stmt = insert(UserContact).values(values)
        upsert_stmt: ReturningInsert[Any] = insert_stmt.on_conflict_do_update(
            index_elements=[UserContact.owner_id, UserContact.contact_id],
            set_={
                "first_name": func.coalesce(insert_stmt.excluded.first_name, UserContact.first_name),
                "last_name": func.coalesce(insert_stmt.excluded.last_name, UserContact.last_name),
                "updated_at": now,
            },
        ).returning(
            UserContact.owner_id,
            UserContact.contact_id,
            literal_column("xmax = 0").label("inserted"),
        )

        result = await self.session.execute(upsert_stmt)
        return {(row.owner_id, row.contact_id) for row in result.all() if row.inserted}

    async def find_forward_contacts(self, owner_id: int, contact_ids: list[int]) -> set[int]:
        if not contact_ids:
            return set()

        stmt = select(UserContact.contact_id).where(
            UserContact.owner_id == owner_id,
            UserContact.contact_id.in_(contact_ids),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def set_mutual_pairs(self, pairs: list[tuple[int, int]]) -> None:
        if not pairs:
            return

        both_directions = [
            pair
            for owner_id, contact_id in pairs
            for pair in ((owner_id, contact_id), (contact_id, owner_id))
        ]

        stmt = (
            update(UserContact)
            .where(
                tuple_(UserContact.owner_id, UserContact.contact_id).in_(both_directions),
                UserContact.is_mutual.is_(False),
            )
            .values(is_mutual=True, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def find_reverse_owners(self, owner_id: int, contact_ids: list[int]) -> set[int]:
        if not contact_ids:
            return set()

        stmt = select(UserContact.owner_id).where(
            UserContact.contact_id == owner_id,
            UserContact.owner_id.in_(contact_ids),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def set_mutual(self, owner_id: int, contact_ids: list[int], is_mutual: bool = True) -> None:
        if not contact_ids:
            return

        stmt = (
            update(UserContact)
            .where(
                or_(
                    and_(
                        UserContact.owner_id == owner_id,
                        UserContact.contact_id.in_(contact_ids),
                    ),
                    and_(
                        UserContact.contact_id == owner_id,
                        UserContact.owner_id.in_(contact_ids),
                    ),
                ),
                UserContact.is_mutual.is_(not is_mutual),
            )
            .values(is_mutual=is_mutual, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def delete(self, owner_id: int, contact_id: int) -> bool:
        stmt = (
            delete(UserContact)
            .where(UserContact.owner_id == owner_id, UserContact.contact_id == contact_id)
            .returning(UserContact.contact_id)
        )
        result = await self.session.execute(stmt)
        if result.scalar() is None:
            return False

        await self.set_mutual(owner_id, [contact_id], is_mutual=False)
        return True

    async def search_own(self, owner_id: int, prefix: str, limit: int) -> list[UserContact]:
        stmt = (
            select(UserContact)
            .outerjoin(
                Profile,
                and_(Profile.id == UserContact.contact_id, Profile.deleted_at.is_(None)),
            )
            .options(selectinload(UserContact.profile))
            .where(
                UserContact.owner_id == owner_id,
                or_(
                    Profile.display_name.istartswith(prefix, autoescape=True),
                    UserContact.first_name.istartswith(prefix, autoescape=True),
                    UserContact.last_name.istartswith(prefix, autoescape=True),
                ),
            )
            .order_by(UserContact.contact_id)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


@dataclass
class ContactIdentifierRepository(IRepository[UserIdentifier], CacheRepository):
    _LIST_VERSION_KEY = "profile:identifiers:list"

    async def consume_quota(self, owner_id: int, amount: int) -> bool:
        if amount <= 0:
            return True

        key = ContactKeys.identifier_quota(owner_id, now_utc().strftime("%Y%m%d"))
        used = await self.redis.incrby(key, amount)
        if used == amount:
            await self.redis.expire(key, profile_config.IDENTIFIER_QUOTA_TTL)

        if used > profile_config.CONTACTS_NEW_IDENTIFIERS_PER_DAY:
            await self.redis.decrby(key, amount)
            return False

        return True

    async def resolve(self, hashes: list[bytes]) -> dict[bytes, int]:
        if not hashes:
            return {}

        stmt = select(UserIdentifier.identifier_hash, UserIdentifier.user_id).where(
            UserIdentifier.identifier_hash.in_(hashes)
        )
        result = await self.session.execute(stmt)
        return {row.identifier_hash: row.user_id for row in result.all()}

    async def upsert(self, identifier_hash: bytes, kind: IdentifierKind, user_id: int) -> None:
        insert_stmt = insert(UserIdentifier).values(
            identifier_hash=identifier_hash,
            kind=int(kind),
            user_id=user_id,
            created_at=now_utc(),
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[UserIdentifier.identifier_hash],
            set_={"user_id": user_id, "kind": int(kind)},
        )
        await self.session.execute(upsert_stmt)

    async def upsert_pending_many(self, owner_id: int, entries: list[PendingUpsert]) -> int:
        if not entries:
            return 0

        now = now_utc()
        values = [
            {
                "owner_id": owner_id,
                "identifier_hash": entry.identifier_hash,
                "first_name": validate_contact_name(entry.first_name),
                "last_name": validate_contact_name(entry.last_name),
                "created_at": now,
            }
            for entry in entries
        ]

        insert_stmt = insert(PendingContact).values(values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[PendingContact.owner_id, PendingContact.identifier_hash],
            set_={
                "first_name": func.coalesce(insert_stmt.excluded.first_name, PendingContact.first_name),
                "last_name": func.coalesce(insert_stmt.excluded.last_name, PendingContact.last_name),
            },
        )
        await self.session.execute(upsert_stmt)
        return len(values)

    async def fetch_pending_batch(
        self, identifier_hash: bytes, limit: int, after_owner_id: int | None = None
    ) -> list[PendingContact]:
        stmt = (
            select(PendingContact)
            .where(PendingContact.identifier_hash == identifier_hash)
            .order_by(PendingContact.owner_id)
            .limit(limit)
        )

        if after_owner_id is not None:
            stmt = stmt.where(PendingContact.owner_id > after_owner_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_pending(self, identifier_hash: bytes, owner_ids: list[int]) -> None:
        if not owner_ids:
            return

        stmt = delete(PendingContact).where(
            PendingContact.identifier_hash == identifier_hash,
            PendingContact.owner_id.in_(owner_ids),
        )
        await self.session.execute(stmt)


@dataclass
class BlockedUserRepository(IRepository[BlockedUser], CacheRepository):
    _LIST_VERSION_KEY = "profile:blocked:list"

    async def get(self, owner_id: int, target_id: int) -> BlockedUser | None:
        stmt = select(BlockedUser).where(
            BlockedUser.owner_id == owner_id, BlockedUser.target_id == target_id
        )
        result = await self.session.execute(stmt)
        return result.scalar()

    async def list_page(
        self, owner_id: int, limit: int, after_target_id: int | None = None
    ) -> tuple[list[BlockedUser], bool]:
        stmt = (
            select(BlockedUser)
            .options(selectinload(BlockedUser.profile))
            .where(BlockedUser.owner_id == owner_id)
            .order_by(BlockedUser.target_id)
            .limit(limit + 1)
        )

        if after_target_id is not None:
            stmt = stmt.where(BlockedUser.target_id > after_target_id)

        result = await self.session.execute(stmt)
        blocked = list(result.scalars().all())

        return blocked[:limit], len(blocked) > limit

    async def all_target_ids(self, owner_id: int) -> list[int]:
        stmt = select(BlockedUser.target_id).where(BlockedUser.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_block_list(self, owner_id: int) -> set[int]:
        key = ContactKeys.block_list(owner_id)
        cached = await self.redis.get(key)

        if cached is not None:
            return set(orjson.loads(cached))

        target_ids = await self.all_target_ids(owner_id)
        await self.redis.set(
            key, orjson.dumps(target_ids), ex=profile_config.BLOCK_LIST_CACHE_TTL
        )
        return set(target_ids)

    async def invalidate_block_list(self, owner_id: int) -> None:
        await self.redis.delete(ContactKeys.block_list(owner_id))
