from pydantic import BaseModel, Field, model_validator

from app.privacy.utils import PrivacyRule, PrivacyVisibility
from app.profiles.config import profile_config


class PrivacyExceptionsRequest(BaseModel):
    allow: list[int] = Field(
        default_factory=list, max_length=profile_config.MAX_PRIVACY_EXCEPTIONS_PER_RULE
    )
    deny: list[int] = Field(
        default_factory=list, max_length=profile_config.MAX_PRIVACY_EXCEPTIONS_PER_RULE
    )


class PrivacySettingsUpdateRequest(BaseModel):
    rules: dict[PrivacyRule, PrivacyVisibility] = Field(default_factory=dict)
    exceptions: dict[PrivacyRule, PrivacyExceptionsRequest] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_not_empty(self) -> PrivacySettingsUpdateRequest:
        if not self.rules and not self.exceptions:
            raise ValueError("rules or exceptions must not be empty")
        return self
