from dataclasses import dataclass
from datetime import date
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy import BigInteger, Date, Index, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.db.base_model import BaseModel, DateMixin, SoftDeleteMixin
from app.core.events.event import BaseEvent
from app.profiles.config import profile_config
from app.profiles.exceptions import TooLongBioError, TooLongDisplayNameError, TooLongSkillNameError
from app.profiles.models.contact import Contact


class SizeAvatar(int, Enum):
    SMALL = 32
    UPPER_SMALL = 64
    MEDIUM = 256
    LARGE = 512


class TypeImageAvatar(StrEnum):
    JPG = "jpg"
    WEBP = "webp"
    AVIF = "avif"


AvatarMap = dict[SizeAvatar, dict[TypeImageAvatar, str]]


@dataclass(frozen=True)
class ProfileCreated(BaseEvent):
    user_id: int
    username: str
    avatars: dict

    display_name: str | None
    bio: str | None
    specialization: str | None
    date_birthday: str | None
    skills: list[str]

    __event_name__: str = "profiles.profile.created"

    def get_partition_key(self) -> str:
        return str(self.user_id)


@dataclass(frozen=True)
class ProfileUpdated(BaseEvent):
    user_id: int
    username: str
    avatars: dict

    display_name: str | None
    bio: str | None
    specialization: str | None
    date_birthday: str | None
    skills: list[str]

    __event_name__: str = "profiles.profile.updated"

    def get_partition_key(self) -> str:
        return str(self.user_id)


class Profile(BaseModel, DateMixin, SoftDeleteMixin):
    __tablename__ = "profiles"
    __table_args__ = (
        Index("idx_profiles_tags", "skills", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)

    avatars: Mapped[AvatarMap] = mapped_column(JSONB, default="{}")
    display_name: Mapped[str | None] = mapped_column(String(profile_config.MAX_LEN_DISPLAY_NAME), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(profile_config.MAX_LEN_BIO), nullable=True)
    specialization: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_birthday: Mapped[date | None] = mapped_column(Date, default=None, nullable=True)

    skills: Mapped[list[str]] = mapped_column(ARRAY(String(profile_config.MAX_LEN_SKILL_NAME)))

    contacts: Mapped[list[Contact]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan"
    )

    @classmethod
    def create(
        cls, user_id: int, username: str,
        display_name: str | None,
        specialization: str | None,
        bio: str | None,
        skills: set[str] | None = None,
        date_birthday: date | None=None,
        contacts: list[Contact] | None=None,
    ) -> Profile:
        instance = cls(
            id=user_id,
            username=username,
            date_birthday=date_birthday,
            specialization=specialization,
            avatars={}
        )
        instance.change_display_name(display_name)
        instance.change_bio(bio)
        instance.update_skills(skills or set())

        if contacts:
            instance.contacts = contacts

        instance.register_event(
            ProfileCreated(
                user_id=instance.id,
                username=instance.username,
                avatars=instance.avatars,
                display_name=instance.display_name,
                bio=instance.bio,
                date_birthday=str(instance.date_birthday) if instance.date_birthday else None,
                skills=instance.skills,
                specialization=instance.specialization
            )
        )

        return instance


    def update(
        self, name: str | None, bio: str | None, specialization: str | None,
        date_birthday: date | None, skills: set[str]
    ) -> None:
        self.change_display_name(name)
        self.change_bio(bio)
        self.change_specialization(specialization)
        self.update_skills(skills or set())
        self.change_birthday(date_birthday)

        self.register_event(
            ProfileUpdated(
                user_id=self.id,
                username=self.username,
                avatars=self.avatars,
                display_name=self.display_name,
                bio=self.bio,
                date_birthday=str(self.date_birthday) if self.date_birthday else None,
                skills=self.skills,
                specialization=self.specialization
            )
        )

    def change_display_name(self, name: str | None) -> None:
        if name and len(name) >= profile_config.MAX_LEN_DISPLAY_NAME:
            raise TooLongDisplayNameError(name=name)

        self.display_name = name

    def change_bio(self, bio: str | None) -> None:
        if bio and len(bio) >= profile_config.MAX_LEN_BIO:
            raise TooLongBioError(bio=bio)

        self.bio = bio

    def change_specialization(self, specialization: str | None) -> None:
        if specialization:
            ...

        self.specialization = specialization

    def change_birthday(self, birthday: date | None) -> None:
        self.date_birthday = birthday

    def add_skill(self, skill: str) -> None:
        if len(skill) > profile_config.MAX_LEN_SKILL_NAME:
            raise TooLongSkillNameError(name=skill)

        self.skills.append(skill.lower())

    def update_skills(self, skills: set[str]) -> None:
        if any(len(skill) > profile_config.MAX_LEN_SKILL_NAME for skill in skills):
            raise TooLongSkillNameError(name=max(skills, key=lambda x: len(x)))

        self.skills = [skill.lower() for skill in skills]

    def add_contact(self, provider: str, contact: str) -> None:
        for cont in self.contacts:
            if provider == cont.provider:
                cont.contact = contact
                return

        self.contacts.append(
            Contact(
                provider=provider,
                contact=contact
            )
        )

    def remove_contact(self, provider: str) -> None:
        self.contacts = [c for c in self.contacts if c.provider != provider]

    def update_avatar(self, avatar_s3_keys: dict) -> None:
        self.avatars = avatar_s3_keys
        self.register_event(
            ProfileUpdated(
                user_id=self.id,
                username=self.username,
                avatars=self.avatars,
                display_name=self.display_name,
                bio=self.bio,
                date_birthday=str(self.date_birthday) if self.date_birthday else None,
                skills=self.skills,
                specialization=self.specialization
            )
        )

    @validates("skills")
    def validate_skills(self, _key: Any, value: list[str]) -> list[str]:

        if len(value) != len(set(value)):
            raise ValueError("Duplicate skills are not allowed")

        for tag in value:
            if len(tag) > profile_config.MAX_LEN_SKILL_NAME:
                raise TooLongSkillNameError(name=tag)

        return value
