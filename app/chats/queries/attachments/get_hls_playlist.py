from dataclasses import dataclass

from app.chats.services.hls import HlsPlaylistService
from app.core.queries import BaseQuery, BaseQueryHandler


@dataclass(frozen=True)
class GetHlsPlaylistQuery(BaseQuery):
    token: str
    name: str


@dataclass(frozen=True)
class GetHlsPlaylistQueryHandler(BaseQueryHandler[GetHlsPlaylistQuery, str]):
    playlist_service: HlsPlaylistService

    async def handle(self, query: GetHlsPlaylistQuery) -> str:
        return await self.playlist_service.render(query.token, query.name)
