from pydantic import BaseModel, ConfigDict


class ChatProfileDTO(BaseModel):
    user_id: int
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None

    avatar_s3_key: str | None = None

    model_config = ConfigDict(from_attributes=True)
