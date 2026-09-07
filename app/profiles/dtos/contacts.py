from pydantic import BaseModel


class ContactDTO(BaseModel):
    profile_id: int
    provider: str
    contact: str

