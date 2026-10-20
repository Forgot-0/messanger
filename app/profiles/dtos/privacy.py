from pydantic import BaseModel, Field

from app.privacy.utils import PrivacyRule, PrivacyVisibility


class PrivacyExceptionsDTO(BaseModel):
    allow: list[int] = Field(default_factory=list)
    deny: list[int] = Field(default_factory=list)


class PrivacySettingsDTO(BaseModel):
    rules: dict[PrivacyRule, PrivacyVisibility]
    exceptions: dict[PrivacyRule, PrivacyExceptionsDTO]

    @classmethod
    def default(cls) -> PrivacySettingsDTO:
        return cls(
            rules=dict.fromkeys(PrivacyRule, PrivacyVisibility.EVERYBODY),
            exceptions={rule: PrivacyExceptionsDTO() for rule in PrivacyRule},
        )
