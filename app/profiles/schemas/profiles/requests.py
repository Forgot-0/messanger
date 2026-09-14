from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.core.api.filter_mapper import FilterMapper
from app.core.filters.pagination import Pagination
from app.profiles.config import profile_config
from app.profiles.filters.profiles import ProfileFilter


class ProfileCreateRequest(BaseModel):
    display_name: str | None = Field(None)
    bio: str | None = Field(None)
    skills: set[str] | None = Field(None)
    date_birthday: date | None = Field(None)


class ProfileUpdateRequest(BaseModel):
    specialization: str | None = Field(None)
    display_name: str | None = Field(None)
    bio: str | None = Field(None)
    skills: set[str] | None = Field(None)
    date_birthday: date | None = Field(None)


class GetProfilesRequest(BaseModel):
    q: str | None = Field(
        default=None,
        max_length=profile_config.PROFILE_SEARCH_MAX_QUERY,
        description="Поиск по username ИЛИ display_name. Не комбинируется с username/display_name.",
    )

    username: str | None = None
    display_name: str | None = None
    skills: list[str] | None = None

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    sort: str | None = Field(default=None, examples=["created_at:desc,username:asc"])

    @model_validator(mode="after")
    def validate_search_query(self) -> GetProfilesRequest:
        if self.q is None:
            return self

        if self.username is not None or self.display_name is not None:
            raise ValueError("q must not be combined with username or display_name")

        query = self.q.strip()
        if len(query) < profile_config.PROFILE_SEARCH_MIN_QUERY:
            raise ValueError(
                f"q must be at least {profile_config.PROFILE_SEARCH_MIN_QUERY} characters long"
            )

        self.q = query
        return self

    def to_profile_filter(self) -> ProfileFilter:
        profile_filter = ProfileFilter(
            username=self.username,
            display_name=self.display_name,
            skills=self.skills
        )

        pagination = Pagination(page=self.page, page_size=self.page_size)
        profile_filter.set_pagination(pagination)

        sort_fields = FilterMapper.parse_sort_string(self.sort)
        for sort_field in sort_fields:
            profile_filter.add_sort(sort_field.field, sort_field.direction)

        return profile_filter


class AvatarUploadCompleteRequest(BaseModel):
    file_key: str


class AvatarPreSignUrlRequest(BaseModel):
    filename: str


class AddProfileLinkRequest(BaseModel):
    provider: str = Field(max_length=30)
    contact: str = Field(max_length=256)

