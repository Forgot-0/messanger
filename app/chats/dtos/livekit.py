from pydantic import BaseModel


class JoinTokenDTO(BaseModel):
    token: str
    slug: str
    livekit_url: str


class LiveKitParticipantsDTO(BaseModel):
    identity: str
    name: str
    state: int
    joined_at: int
