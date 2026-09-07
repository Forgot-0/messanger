from dataclasses import dataclass

from app.chats.schemas.ws import WSClientOp
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.websocket import WSConnection


@dataclass(frozen=True)
class UnsubscribeCommand(BaseCommand):
    conn: WSConnection
    chat_id: str
    op: WSClientOp = WSClientOp.UNSUBSCRIBE


@dataclass(frozen=True)
class UnsubscribeCommandHandler(BaseCommandHandler[UnsubscribeCommand, None]):
    manager: ConnectionManager

    async def handle(self, command: UnsubscribeCommand) -> None:
        await self.manager.unsubscribe_channel(command.conn, command.chat_id)
        command.conn.try_send({
            "type": "ws.unsubscribed",
            "chat_id": command.chat_id,
            "payload": {},
        })

