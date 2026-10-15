from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Path, Response, status

from app.chats.config import chat_config
from app.chats.queries.attachments.get_hls_playlist import GetHlsPlaylistQuery
from app.core.mediators.base import BaseMediator

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/{token}/{name}",
    status_code=status.HTTP_200_OK,
    response_class=Response,
)
async def get_hls_playlist(
    token: Annotated[str, Path(max_length=512)],
    name: Annotated[str, Path(max_length=32)],
    mediator: FromDishka[BaseMediator],
) -> Response:
    playlist = await mediator.handle_query(GetHlsPlaylistQuery(token=token, name=name))
    return Response(
        content=playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": f"private, max-age={min(300, chat_config.HLS_URL_TTL)}"},
    )
