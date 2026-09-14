import hashlib
from dataclasses import dataclass

from app.chats.config import chat_config
from app.chats.dtos.reactions import ReactionsCatalogDTO
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetReactionsCatalogQuery(BaseQuery):
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class GetReactionsCatalogQueryHandler(
    BaseQueryHandler[GetReactionsCatalogQuery, ReactionsCatalogDTO]
):
    async def handle(
        self,
        query: GetReactionsCatalogQuery,  # noqa: ARG002
    ) -> ReactionsCatalogDTO:
        emojis = list(chat_config.DEFAULT_REACTIONS)

        version = hashlib.sha256(
            "\x1f".join(emojis).encode("utf-8")
        ).hexdigest()[:16]

        return ReactionsCatalogDTO(
            emojis=emojis,
            max_reactions_per_user_per_message=(
                chat_config.MAX_REACTIONS_PER_USER_PER_MESSAGE
            ),
            max_distinct_reactions_per_message=(
                chat_config.MAX_DISTINCT_REACTIONS_PER_MESSAGE
            ),
            max_reaction_length=chat_config.MAX_REACTION_LENGTH,
            version=version,
        )
