from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.profiles.models.contacts import ContactSource


class ImportStatus(StrEnum):
    DONE = "done"
    QUEUED = "queued"


class ContactProfileDTO(BaseModel):
    id: int
    username: str | None = None
    display_name: str | None = None
    avatars: dict[Any, dict[Any, str]] = {}

    model_config = ConfigDict(from_attributes=True)


class UserContactDTO(BaseModel):
    owner_id: int
    contact_id: int

    first_name: str | None = None
    last_name: str | None = None

    source: ContactSource
    is_mutual: bool
    is_favorite: bool

    created_at: datetime
    updated_at: datetime

    profile: ContactProfileDTO | None = None

    model_config = ConfigDict(from_attributes=True)


class ContactListDTO(BaseModel):
    contacts: list[UserContactDTO]
    has_next: bool
    next_contact_id: int | None = None
    version: datetime | None = None


class BlockedUserDTO(BaseModel):
    target_id: int
    created_at: datetime

    profile: ContactProfileDTO | None = None

    model_config = ConfigDict(from_attributes=True)


class BlockedListDTO(BaseModel):
    blocked: list[BlockedUserDTO]
    has_next: bool
    next_target_id: int | None = None


class ContactSearchItemDTO(BaseModel):
    user_id: int
    profile: ContactProfileDTO | None = None
    contact: UserContactDTO | None = None


class ContactSearchDTO(BaseModel):
    items: list[ContactSearchItemDTO]


class ImportContactsResultDTO(BaseModel):
    status: ImportStatus
    accepted: int
    matched: int = 0
    pending: int = 0
    invalid: int = 0
    contacts: list[UserContactDTO] = []


class ImportCompletedPayload(BaseModel):
    owner_id: int
    matched: int
    pending: int
    invalid: int
    accepted: int
