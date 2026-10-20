from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base_model import BaseModel, DateMixin
from app.core.events.event import BaseEvent
from app.privacy.utils import DEFAULT_VISIBILITY, PrivacyRule, PrivacyVisibility
from app.profiles.config import profile_config
from app.profiles.exceptions import PrivacyExceptionsLimitError


@dataclass(frozen=True)
class PrivacyUpdated(BaseEvent):
    user_id: int
    rules: dict[str, str]
    exceptions: dict[str, dict[str, list[int]]]

    __event_name__: str = "profiles.privacy.updated"

    def get_aggregate_id(self) -> str:
        return str(self.user_id)


def _visibility_column() -> Mapped[PrivacyVisibility]:
    return mapped_column(
        Enum(PrivacyVisibility, native_enum=False, length=16),
        default=DEFAULT_VISIBILITY,
        server_default=DEFAULT_VISIBILITY.value,
        nullable=False,
    )


class ProfilePrivacyException(BaseModel):
    __tablename__ = "profile_privacy_exceptions"

    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile_privacy.user_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    rule: Mapped[PrivacyRule] = mapped_column(
        Enum(PrivacyRule, native_enum=False, length=16), primary_key=True
    )
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    allow: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ProfilePrivacy(BaseModel, DateMixin):
    __tablename__ = "profile_privacy"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    last_seen: Mapped[PrivacyVisibility] = _visibility_column()
    photo: Mapped[PrivacyVisibility] = _visibility_column()
    messages: Mapped[PrivacyVisibility] = _visibility_column()
    group_invites: Mapped[PrivacyVisibility] = _visibility_column()
    calls: Mapped[PrivacyVisibility] = _visibility_column()

    exceptions: Mapped[list[ProfilePrivacyException]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    @classmethod
    def create(cls, user_id: int) -> ProfilePrivacy:
        instance = cls(user_id=user_id)
        for rule in PrivacyRule:
            instance.set_rule(rule, DEFAULT_VISIBILITY)
        instance.exceptions = []
        return instance

    def visibility(self, rule: PrivacyRule) -> PrivacyVisibility:
        return PrivacyVisibility(getattr(self, rule.value))

    def set_rule(self, rule: PrivacyRule, visibility: PrivacyVisibility) -> None:
        setattr(self, rule.value, visibility)

    def replace_exceptions(
        self, rule: PrivacyRule, allow: Iterable[int], deny: Iterable[int]
    ) -> None:
        allowed = {int(user_id) for user_id in allow if int(user_id) != self.user_id}
        denied = {int(user_id) for user_id in deny if int(user_id) != self.user_id} - allowed

        total = len(allowed) + len(denied)
        if total > profile_config.MAX_PRIVACY_EXCEPTIONS_PER_RULE:
            raise PrivacyExceptionsLimitError(
                rule=rule.value,
                limit=profile_config.MAX_PRIVACY_EXCEPTIONS_PER_RULE,
                current=total,
            )

        self.exceptions = [
            item for item in self.exceptions if item.rule is not rule
        ] + [
            ProfilePrivacyException(
                owner_id=self.user_id, rule=rule, target_id=target_id, allow=True
            )
            for target_id in sorted(allowed)
        ] + [
            ProfilePrivacyException(
                owner_id=self.user_id, rule=rule, target_id=target_id, allow=False
            )
            for target_id in sorted(denied)
        ]

    def rules_snapshot(self) -> dict[str, str]:
        return {rule.value: self.visibility(rule).value for rule in PrivacyRule}

    def exceptions_snapshot(self) -> dict[str, dict[str, list[int]]]:
        snapshot: dict[str, dict[str, list[int]]] = {
            rule.value: {"allow": [], "deny": []} for rule in PrivacyRule
        }
        for item in self.exceptions:
            bucket = "allow" if item.allow else "deny"
            snapshot[PrivacyRule(item.rule).value][bucket].append(int(item.target_id))

        for buckets in snapshot.values():
            buckets["allow"].sort()
            buckets["deny"].sort()

        return snapshot

    def register_updated(self) -> None:
        self.register_event(
            PrivacyUpdated(
                user_id=self.user_id,
                rules=self.rules_snapshot(),
                exceptions=self.exceptions_snapshot(),
            )
        )
