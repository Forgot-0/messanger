from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    TypeDecorator,
    and_,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db.base_model import BaseModel, DateMixin
from app.core.events.event import BaseEvent
from app.core.utils import now_utc
from app.profiles.config import profile_config
from app.profiles.exceptions import TooLongContactNameError
from app.profiles.models.profile import Profile


class ContactSource(IntEnum):
    IMPORT = 1
    USERNAME = 2
    INVITE = 3
    MANUAL = 4


class IdentifierKind(IntEnum):
    EMAIL = 1
    PHONE = 2


class IntEnumType(TypeDecorator):
    impl = SmallInteger
    cache_ok = True

    def __init__(self, enum_class: type[IntEnum], *args: Any, **kwargs: Any) -> None:
        self.enum_class = enum_class
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value: Any, _dialect: Dialect) -> int | None:
        if value is None:
            return None
        return int(self.enum_class(value))

    def process_result_value(self, value: Any, _dialect: Dialect) -> IntEnum | None:
        if value is None:
            return None
        return self.enum_class(value)

    def process_literal_param(self, value: Any, _dialect: Dialect) -> str:
        return str(int(self.enum_class(value)))

    @property
    def python_type(self) -> type[IntEnum]:
        return self.enum_class


@dataclass(frozen=True)
class ContactAdded(BaseEvent):
    owner_id: int
    contact_id: int
    source: int
    is_mutual: bool

    __event_name__: str = "profiles.contact.added"

    def get_partition_key(self) -> str:
        return str(self.owner_id)


@dataclass(frozen=True)
class ContactRemoved(BaseEvent):
    owner_id: int
    contact_id: int

    __event_name__: str = "profiles.contact.removed"

    def get_partition_key(self) -> str:
        return str(self.owner_id)


@dataclass(frozen=True)
class UserBlocked(BaseEvent):
    owner_id: int
    target_id: int

    __event_name__: str = "profiles.user.blocked"

    def get_partition_key(self) -> str:
        return str(self.owner_id)


@dataclass(frozen=True)
class UserUnblocked(BaseEvent):
    owner_id: int
    target_id: int

    __event_name__: str = "profiles.user.unblocked"

    def get_partition_key(self) -> str:
        return str(self.owner_id)


def validate_contact_name(name: str | None) -> str | None:
    if name is None:
        return None

    cleaned = name.strip()
    if not cleaned:
        return None

    if len(cleaned) > profile_config.MAX_LEN_CONTACT_NAME:
        raise TooLongContactNameError(name=cleaned)

    return cleaned


class UserContact(BaseModel, DateMixin):
    __tablename__ = "user_contacts"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    contact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    first_name: Mapped[str | None] = mapped_column(
        String(profile_config.MAX_LEN_CONTACT_NAME), nullable=True
    )
    last_name: Mapped[str | None] = mapped_column(
        String(profile_config.MAX_LEN_CONTACT_NAME), nullable=True
    )

    source: Mapped[ContactSource] = mapped_column(IntEnumType(ContactSource), nullable=False)
    is_mutual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    profile: Mapped[Profile | None] = relationship(
        "Profile",
        primaryjoin=lambda: and_(
            foreign(UserContact.contact_id) == Profile.id,
            Profile.deleted_at.is_(None),
        ),
        viewonly=True,
        lazy="raise",
    )
    owner_profile: Mapped[Profile | None] = relationship(
        "Profile",
        primaryjoin=lambda: and_(
            foreign(UserContact.owner_id) == Profile.id,
            Profile.deleted_at.is_(None),
        ),
        viewonly=True,
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_user_contacts_contact_owner", "contact_id", "owner_id"),
        Index("ix_user_contacts_owner_updated", "owner_id", "updated_at"),
    )

    @classmethod
    def create(
        cls,
        owner_id: int,
        contact_id: int,
        source: ContactSource,
        first_name: str | None = None,
        last_name: str | None = None,
        is_mutual: bool = False,
    ) -> UserContact:
        instance = cls(
            owner_id=owner_id,
            contact_id=contact_id,
            source=source,
            first_name=validate_contact_name(first_name),
            last_name=validate_contact_name(last_name),
            is_mutual=is_mutual,
            is_favorite=False,
        )
        instance.register_event(
            ContactAdded(
                owner_id=owner_id,
                contact_id=contact_id,
                source=int(source),
                is_mutual=is_mutual,
            )
        )
        return instance

    def rename(self, first_name: str | None, last_name: str | None) -> None:
        first = validate_contact_name(first_name)
        last = validate_contact_name(last_name)

        if (first, last) == (self.first_name, self.last_name):
            return

        self.first_name = first
        self.last_name = last
        self.touch()

    def mark_favorite(self, is_favorite: bool) -> None:
        if self.is_favorite == is_favorite:
            return

        self.is_favorite = is_favorite
        self.touch()

    def touch(self) -> None:
        self.updated_at = now_utc()

    def register_removed(self) -> None:
        self.register_event(
            ContactRemoved(owner_id=self.owner_id, contact_id=self.contact_id)
        )


class UserIdentifier(BaseModel):
    __tablename__ = "user_identifiers"

    identifier_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    kind: Mapped[IdentifierKind] = mapped_column(IntEnumType(IdentifierKind), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile: Mapped[Profile | None] = relationship(
        "Profile",
        primaryjoin=lambda: foreign(UserIdentifier.user_id) == Profile.id,
        viewonly=True,
        lazy="raise",
    )


class PendingContact(BaseModel):
    __tablename__ = "pending_contacts"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    identifier_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)

    first_name: Mapped[str | None] = mapped_column(
        String(profile_config.MAX_LEN_CONTACT_NAME), nullable=True
    )
    last_name: Mapped[str | None] = mapped_column(
        String(profile_config.MAX_LEN_CONTACT_NAME), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_pending_contacts_identifier", "identifier_hash"),
    )


class BlockedUser(BaseModel):
    __tablename__ = "blocked_users"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile: Mapped[Profile | None] = relationship(
        "Profile",
        primaryjoin=lambda: and_(
            foreign(BlockedUser.target_id) == Profile.id,
            Profile.deleted_at.is_(None),
        ),
        viewonly=True,
        lazy="raise",
    )

    @classmethod
    def create(cls, owner_id: int, target_id: int) -> BlockedUser:
        instance = cls(owner_id=owner_id, target_id=target_id)
        instance.register_event(UserBlocked(owner_id=owner_id, target_id=target_id))
        return instance

    def register_unblocked(self) -> None:
        self.register_event(UserUnblocked(owner_id=self.owner_id, target_id=self.target_id))
