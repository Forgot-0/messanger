import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid7

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.chats.config import chat_config
from app.chats.dtos.avatars import pick_avatar_key
from app.chats.exceptions import (
    AccessDeniedChatError,
    ChatUsernameNotAllowedError,
    InvalidChatUsernameError,
    InvalidMessageError,
    InvalidOwnershipTransferError,
    MemberLimitExceededError,
    NotFoundMessageError,
    PinnedMessagesLimitExceededError,
    ReactionNotAllowedError,
    SlowModeOutOfRangeError,
)
from app.chats.models.chat_members import ChatMember
from app.chats.models.chat_roles import ChatRoleId
from app.chats.models.message import Message, MessageType, PinnedMessageEvent, UnpinnedMessagesEvent
from app.chats.models.pinned_message import ChatPinnedMessage
from app.core.db.base_model import BaseModel, DateMixin, SoftDeleteMixin
from app.core.events.event import BaseEvent


class ChatType(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class ChatReactionsMode(StrEnum):
    ALL = "all"
    SOME = "some"
    NONE = "none"


class ChatFanoutStrategy(StrEnum):
    FANOUT_ON_WRITE = "fanout_on_write"
    ACTIVE_SUBSCRIBERS = "active_subscribers"
    CHANNEL_SUBSCRIBERS = "channel_subscribers"


@dataclass(frozen=True)
class CreatedChatEvent(BaseEvent):
    chat_id: str
    created_by: int
    name: str | None
    member_ids: list[int]
    chat_type: str
    member_count: int

    __event_name__ = "chats.chat.created"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class UpdatedChatEvent(BaseEvent):
    chat_id: str
    updated_by: int
    name: str | None
    description: str | None
    is_public: bool
    admin_only: bool
    slow_mode_seconds: int
    permissions: dict[str, bool]
    reactions_mode: str
    allowed_reactions: list[str]
    username: str | None = None
    avatar_s3_key: str | None = None
    avatars: dict[str, dict[str, str]] = field(default_factory=dict)

    __event_name__ = "chats.chat.updated"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class TransferredChatOwnershipEvent(BaseEvent):
    chat_id: str
    requester_id: int
    previous_owner_id: int
    new_owner_id: int

    __event_name__ = "chats.chat.ownership_transferred"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class DeletedChatEvent(BaseEvent):
    chat_id: str
    deleted_by: int

    __event_name__ = "chats.chat.deleted"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class AddedChatMemberEvent(BaseEvent):
    chat_id: str
    user_id: int
    role_id: int

    __event_name__ = "chats.member.added"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class KickedChatMemberEvent(BaseEvent):
    chat_id: str
    requester_id: int
    target_user_id: int

    __event_name__ = "chats.member.kicked"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class BannedChatMemberEvent(BaseEvent):
    chat_id: str
    requester_id: int
    target_user_id: int
    ban: bool

    __event_name__ = "chats.member.banned"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class MutedChatMemberEvent(BaseEvent):
    chat_id: str
    requester_id: int
    target_user_id: int
    mute: bool
    muted_until: str | None

    __event_name__ = "chats.member.muted"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class LeftChatMemberEvent(BaseEvent):
    chat_id: str
    user_id: int

    __event_name__ = "chats.member.left"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]$")


class Chat(BaseModel, DateMixin, SoftDeleteMixin):
    __tablename__ = "chats"

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), primary_key=True)
    seq_counter: Mapped[int] = mapped_column(BigInteger, default=0)

    type: Mapped[ChatType] = mapped_column(Enum(ChatType), nullable=False)
    name: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(String(1024))
    username: Mapped[str | None] = mapped_column(
        String(chat_config.CHAT_USERNAME_MAX_LENGTH), nullable=True, default=None
    )
    avatar_s3_key: Mapped[str | None] = mapped_column(String(512))
    avatars: Mapped[dict[str, dict[str, str]]] = mapped_column(
        JSONB, server_default="{}", default=dict, nullable=False
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0)

    admin_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    slow_mode_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    permissions: Mapped[dict[str, bool]] = mapped_column(JSONB, server_default="{}", default=dict)

    reactions_mode: Mapped[ChatReactionsMode] = mapped_column(
        Enum(ChatReactionsMode),
        default=ChatReactionsMode.ALL,
        nullable=False,
    )
    allowed_reactions: Mapped[list[str]] = mapped_column(
        JSONB, server_default="[]", default=list, nullable=False
    )

    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    members: Mapped[list[ChatMember]] = relationship(back_populates="chat", lazy="noload")
    messages: Mapped[list[Message]] = relationship(
        back_populates="chat", foreign_keys=[Message.chat_id], lazy="noload"
    )

    __table_args__ = (
        Index("ix_chats_type_public", "type", "is_public"),
        Index("ix_chats_type_member_count", "type", "member_count"),
        Index(
            "uq_chats_username_lower",
            text("lower(username) text_pattern_ops"),
            unique=True,
            postgresql_where=text("username IS NOT NULL"),
        ),
        Index(
            "ix_chats_public_name_fts_simple",
            text("to_tsvector('simple', coalesce(name, ''))"),
            postgresql_using="gin",
            postgresql_where=text("is_public AND deleted_at IS NULL"),
        ),
    )

    @staticmethod
    def member_limit(chat_type: ChatType) -> int:
        if chat_type == ChatType.DIRECT:
            return 2
        if chat_type == ChatType.GROUP:
            return chat_config.MAX_GROUP_MEMBERS
        if chat_type == ChatType.SUPERGROUP:
            return chat_config.MAX_SUPERGROUP_MEMBERS
        if chat_type == ChatType.CHANNEL:
            return chat_config.MAX_CHANNEL_SUBSCRIBERS
        return chat_config.MAX_MEMBERS

    @staticmethod
    def resolve_fanout_strategy(
        chat_type: ChatType, member_count: int
    ) -> ChatFanoutStrategy:
        if chat_type == ChatType.CHANNEL:
            return ChatFanoutStrategy.CHANNEL_SUBSCRIBERS
        if chat_type == ChatType.SUPERGROUP:
            return ChatFanoutStrategy.ACTIVE_SUBSCRIBERS
        if chat_type == ChatType.GROUP and member_count > chat_config.FAN_OUT_WRITE_THRESHOLD:
            return ChatFanoutStrategy.ACTIVE_SUBSCRIBERS
        return ChatFanoutStrategy.FANOUT_ON_WRITE

    @property
    def fanout_strategy(self) -> ChatFanoutStrategy:
        return self.resolve_fanout_strategy(self.type, self.member_count)

    @property
    def support_read_event(self) -> bool:
        return self.type == ChatType.DIRECT or self.type == ChatType.GROUP

    @property
    def is_small_group(self) -> bool:
        return self.member_count <= chat_config.READ_MARKS_MAX_MEMBERS

    @property
    def tracks_read_marks(self) -> bool:
        return self.type in (ChatType.GROUP, ChatType.SUPERGROUP) and self.is_small_group

    @classmethod
    def create(
        cls,
        created_by: int,
        members_ids: list[int],
        chat_type: ChatType = ChatType.DIRECT,
        name: str | None = None,
        description: str | None = None,
        is_public: bool = False,
        admin_only: bool = False,
        slow_mode_seconds: int = 0,
        permissions: dict[str, bool] | None = None,
    ) -> Self:
        if created_by in members_ids:
            members_ids.remove(created_by)

        if chat_type == ChatType.DIRECT and (len(members_ids) != 1 or created_by == members_ids[0]):
            raise MemberLimitExceededError(limit=2)

        if len(members_ids) > 200_000:
            raise MemberLimitExceededError(limit=200_000)

        participant_count = len(members_ids) + 1
        limit = cls.member_limit(chat_type)
        if participant_count > limit:
            raise MemberLimitExceededError(limit=limit)

        cls._validate_slow_mode(slow_mode_seconds)

        instance = cls(
            id=uuid7(),
            created_by=created_by,
            type=chat_type,
            name=name,
            description=description,
            is_public=is_public,
            admin_only=admin_only,
            slow_mode_seconds=slow_mode_seconds,
            member_count=0,
            permissions=permissions or {},
            reactions_mode=ChatReactionsMode.ALL,
            allowed_reactions=[],
            username=None,
            avatars={},
        )

        if chat_type == ChatType.DIRECT:
            instance.add_member(created_by, ChatRoleId.DIRECT_MEMBER)
            instance.add_member(members_ids[0], ChatRoleId.DIRECT_MEMBER)

        elif chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
            instance.add_member(created_by, ChatRoleId.OWNER)
            for m_id in members_ids:
                instance.add_member(m_id, ChatRoleId.MEMBER)

        elif chat_type == ChatType.CHANNEL:
            instance.add_member(created_by, ChatRoleId.OWNER)
            for m_id in members_ids:
                instance.add_member(m_id, ChatRoleId.VIEWER)

        instance.member_count = len(instance.members)

        instance.register_event(
            CreatedChatEvent(
                chat_id=str(instance.id),
                created_by=created_by,
                name=name,
                member_ids=members_ids,
                chat_type=chat_type.value,
                member_count=instance.member_count,
            )
        )

        return instance

    def update(
        self,
        updated_by: int,
        name: str | None,
        description: str | None,
        is_public: bool | None,
        admin_only: bool | None = None,
        slow_mode_seconds: int | None = None,
        permissions: dict[str, bool] | None = None,
        reactions_mode: ChatReactionsMode | None = None,
        allowed_reactions: list[str] | None = None,
    ) -> None:
        if slow_mode_seconds is not None:
            self._validate_slow_mode(slow_mode_seconds)
            self.slow_mode_seconds = slow_mode_seconds

        if admin_only is not None:
            self.admin_only = admin_only

        if permissions is not None:
            self.permissions = permissions

        if reactions_mode is not None:
            self.reactions_mode = reactions_mode

        if allowed_reactions is not None:
            self._validate_allowed_reactions(allowed_reactions)
            self.allowed_reactions = allowed_reactions

        if name is not None:
            self.name = name

        if description is not None:
            self.description = description

        if is_public is not None:
            self.is_public = is_public
            if not is_public:
                self.username = None

        self._register_updated(updated_by)

    def set_username(self, updated_by: int, username: str | None) -> None:
        if username is None:
            self.username = None
            self._register_updated(updated_by)
            return

        if self.type == ChatType.DIRECT:
            raise ChatUsernameNotAllowedError(chat_id=str(self.id), reason="direct_chat")

        if not self.is_public:
            raise ChatUsernameNotAllowedError(chat_id=str(self.id), reason="chat_not_public")

        self.username = self.validate_username(username)
        self._register_updated(updated_by)

    def update_avatar(self, updated_by: int, avatars: dict[str, dict[str, str]]) -> None:
        self.avatars = avatars
        self.avatar_s3_key = pick_avatar_key(avatars)
        self._register_updated(updated_by)

    def transfer_ownership(self, requester_id: int, new_owner: ChatMember) -> int:
        if self.type == ChatType.DIRECT:
            raise InvalidOwnershipTransferError(chat_id=str(self.id), reason="direct_chat")

        if new_owner.user_id == self.created_by:
            raise InvalidOwnershipTransferError(chat_id=str(self.id), reason="already_owner")

        if new_owner.is_banned:
            raise InvalidOwnershipTransferError(chat_id=str(self.id), reason="target_banned")

        previous_owner_id = self.created_by
        self.created_by = new_owner.user_id
        new_owner.role_id = ChatRoleId.OWNER

        self.register_event(
            TransferredChatOwnershipEvent(
                chat_id=str(self.id),
                requester_id=requester_id,
                previous_owner_id=previous_owner_id,
                new_owner_id=new_owner.user_id,
            )
        )
        return previous_owner_id

    @staticmethod
    def validate_username(username: str) -> str:
        cleaned = username.strip().removeprefix("@")

        if not (
            chat_config.CHAT_USERNAME_MIN_LENGTH
            <= len(cleaned)
            <= chat_config.CHAT_USERNAME_MAX_LENGTH
        ):
            raise InvalidChatUsernameError(username=username, reason="length")

        if not _USERNAME_RE.fullmatch(cleaned):
            raise InvalidChatUsernameError(username=username, reason="format")

        if cleaned.lower() in chat_config.CHAT_USERNAME_RESERVED:
            raise InvalidChatUsernameError(username=username, reason="reserved")

        return cleaned

    def _register_updated(self, updated_by: int) -> None:
        self.register_event(
            UpdatedChatEvent(
                chat_id=str(self.id),
                updated_by=updated_by,
                name=self.name,
                description=self.description,
                is_public=self.is_public,
                admin_only=self.admin_only,
                slow_mode_seconds=self.slow_mode_seconds,
                permissions=self.permissions or {},
                reactions_mode=self.reactions_mode.value,
                allowed_reactions=list(self.allowed_reactions or []),
                username=self.username,
                avatar_s3_key=self.avatar_s3_key,
                avatars=dict(self.avatars or {}),
            )
        )

    def pin_message(self, message: Message, pinned_by: int, pinned_count: int) -> ChatPinnedMessage:
        if message.chat_id != self.id or message.is_deleted:
            raise NotFoundMessageError(message_id=str(message.id))

        if message.type == MessageType.SYSTEM:
            raise InvalidMessageError(reason="system messages cannot be pinned")

        if pinned_count >= chat_config.MAX_PINNED_MESSAGES:
            raise PinnedMessagesLimitExceededError(
                chat_id=str(self.id), limit=chat_config.MAX_PINNED_MESSAGES
            )

        pin = ChatPinnedMessage.create(
            chat_id=self.id,
            message_id=message.id,
            message_seq=message.seq,
            pinned_by=pinned_by,
        )
        self.register_event(
            PinnedMessageEvent(
                chat_id=str(self.id),
                message_id=str(message.id),
                seq=message.seq,
                pinned_by=pinned_by,
                pinned_at=pin.pinned_at.isoformat(),
            )
        )
        return pin

    def unpin_messages(
        self,
        message_ids: Sequence[UUID],
        unpinned_by: int,
        unpin_all: bool = False,
    ) -> None:
        if not message_ids:
            return

        self.register_event(
            UnpinnedMessagesEvent(
                chat_id=str(self.id),
                message_ids=[str(message_id) for message_id in message_ids],
                unpinned_by=unpinned_by,
                all=unpin_all,
            )
        )

    def delete(self, deleted_by: int) -> None:
        self.soft_delete()
        self.register_event(
            DeletedChatEvent(
                chat_id=str(self.id),
                deleted_by=deleted_by,
            )
        )

    def add_member(self, member_id: int, role_id: int) -> None:
        self.members.append(
            ChatMember.create(chat_id=self.id, user_id=member_id, role_id=role_id)
        )
        self.register_event(
            AddedChatMemberEvent(
                chat_id=str(self.id),
                user_id=member_id,
                role_id=int(role_id),
            )
        )

    def leave(self, user_id: int) -> None:
        if self.created_by == user_id:
            raise AccessDeniedChatError(chat_id=str(self.id), requester_id=user_id)

        self.register_event(LeftChatMemberEvent(
            chat_id=str(self.id),
            user_id=user_id,
        ))

    def kick_member(self, target: int, requester_id: int) -> None:
        if target == requester_id:
            raise AccessDeniedChatError(chat_id=str(self.id), requester_id=requester_id)

        self.register_event(KickedChatMemberEvent(
            chat_id=str(self.id),
            requester_id=requester_id,
            target_user_id=target
        ))

    def ban_member(self, target: int, requester_id: int, ban: bool) -> None:
        if target == requester_id:
            raise AccessDeniedChatError(chat_id=str(self.id), requester_id=requester_id)

        self.register_event(BannedChatMemberEvent(
            chat_id=str(self.id),
            requester_id=requester_id,
            target_user_id=target,
            ban=ban,
        ))

    def mute_member(self, target: ChatMember, requester_id: int) -> None:
        if target.user_id == requester_id:
            raise AccessDeniedChatError(chat_id=str(self.id), requester_id=requester_id)

        self.register_event(MutedChatMemberEvent(
            chat_id=str(self.id),
            requester_id=requester_id,
            target_user_id=target.user_id,
            mute=target.is_muted,
            muted_until=target.muted_until.isoformat() if target.is_muted and target.muted_until else None,
        ))

    @staticmethod
    def _validate_slow_mode(slow_mode_seconds: int) -> None:
        if slow_mode_seconds < 0 or slow_mode_seconds > chat_config.MAX_SLOW_MODE_SECONDS:
            raise SlowModeOutOfRangeError(seconds=slow_mode_seconds)

    @staticmethod
    def _validate_allowed_reactions(allowed_reactions: list[str]) -> None:

        if len(allowed_reactions) > chat_config.MAX_DISTINCT_REACTIONS_PER_MESSAGE:
            raise ReactionNotAllowedError(
                emoji="", allowed=sorted(chat_config.DEFAULT_REACTIONS)
            )

        unknown = [e for e in allowed_reactions if e not in chat_config.DEFAULT_REACTIONS]
        if unknown:
            raise ReactionNotAllowedError(
                emoji=unknown[0], allowed=sorted(chat_config.DEFAULT_REACTIONS)
            )
