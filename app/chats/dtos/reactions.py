from uuid import UUID

from pydantic import BaseModel, Field


class ReactionGroupDTO(BaseModel):
    emoji: str
    count: int
    reacted_by_me: bool = False
    recent_user_ids: list[int] = Field(default_factory=list)


class MessageReactionsDTO(BaseModel):
    message_id: UUID
    groups: list[ReactionGroupDTO] = Field(default_factory=list)

    emoji: str | None = None
    users: list[int] = Field(default_factory=list)
    has_next: bool = False
    next_user_id: int | None = None


class ReactionUpdateWSDTO(BaseModel):
    message_id: UUID
    chat_id: UUID
    actor_id: int
    action: str
    groups: list[ReactionGroupDTO] = Field(default_factory=list)


class ReactionsCatalogDTO(BaseModel):
    emojis: list[str]
    max_reactions_per_user_per_message: int
    max_distinct_reactions_per_message: int
    max_reaction_length: int
    version: str
