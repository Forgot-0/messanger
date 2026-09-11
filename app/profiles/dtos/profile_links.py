from pydantic import BaseModel, ConfigDict


class ProfileLinkDTO(BaseModel):
    profile_id: int
    provider: str
    contact: str

    model_config = ConfigDict(from_attributes=True)
