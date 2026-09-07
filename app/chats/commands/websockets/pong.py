from dataclasses import dataclass

from app.chats.schemas.ws import WSClientOp
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.websocket.websocket import WSConnection


@dataclass(frozen=True)
class PongCommand(BaseCommand):
    conn: WSConnection
    op: WSClientOp = WSClientOp.PONG


@dataclass(frozen=True)
class PongCommandHandler(BaseCommandHandler[PongCommand, None]):
    async def handle(self, command: PongCommand) -> None:
        command.conn.touch()



