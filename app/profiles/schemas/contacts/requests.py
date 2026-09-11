from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.profiles.commands.contacts.import_batch import ImportContactEntry
from app.profiles.config import profile_config


class AddContactRequest(BaseModel):
    user_id: int | None = Field(default=None, ge=1)
    username: str | None = Field(default=None, max_length=150)

    first_name: str | None = Field(default=None, max_length=profile_config.MAX_LEN_CONTACT_NAME)
    last_name: str | None = Field(default=None, max_length=profile_config.MAX_LEN_CONTACT_NAME)

    @model_validator(mode="after")
    def validate_target(self) -> AddContactRequest:
        if self.user_id is None and not self.username:
            raise ValueError("user_id or username is required")
        return self


class UpdateContactRequest(BaseModel):
    first_name: str | None = Field(default=None, max_length=profile_config.MAX_LEN_CONTACT_NAME)
    last_name: str | None = Field(default=None, max_length=profile_config.MAX_LEN_CONTACT_NAME)
    is_favorite: bool | None = Field(default=None)


class ImportContactItem(BaseModel):
    email: str = Field(max_length=320)
    first_name: str | None = Field(default=None, max_length=profile_config.MAX_LEN_CONTACT_NAME)
    last_name: str | None = Field(default=None, max_length=profile_config.MAX_LEN_CONTACT_NAME)

    def to_entry(self) -> ImportContactEntry:
        return ImportContactEntry(
            email=self.email, first_name=self.first_name, last_name=self.last_name
        )


class ImportContactsRequest(BaseModel):
    contacts: list[ImportContactItem] = Field(
        min_length=1, max_length=profile_config.CONTACTS_IMPORT_MAX_BATCH
    )

    def to_entries(self) -> list[ImportContactEntry]:
        return [item.to_entry() for item in self.contacts]


class GetContactsRequest(BaseModel):
    limit: int = Field(
        default=profile_config.CONTACTS_PAGE_SIZE,
        ge=1,
        le=profile_config.CONTACTS_MAX_PAGE_SIZE,
    )
    after_contact_id: int | None = Field(default=None, ge=1)
    updated_after: datetime | None = Field(default=None)


class SearchContactsRequest(BaseModel):
    query: str = Field(min_length=1, max_length=150)
    limit: int = Field(default=profile_config.CONTACTS_SEARCH_LIMIT, ge=1, le=profile_config.CONTACTS_SEARCH_LIMIT)


class GetBlockedRequest(BaseModel):
    limit: int = Field(
        default=profile_config.CONTACTS_PAGE_SIZE,
        ge=1,
        le=profile_config.CONTACTS_MAX_PAGE_SIZE,
    )
    after_target_id: int | None = Field(default=None, ge=1)
