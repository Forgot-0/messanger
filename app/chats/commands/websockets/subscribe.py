from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.messages import MessageDTO
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.schemas.ws import WSClientOp
from app.chats.services.messages import MessageService
from app.chats.services.reaction_attach import ReactionAttachService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.websocket import WSConnection


@dataclass(frozen=True)
class SubscribeCommand(BaseCommand):
    conn: WSConnection
    chat_id: str
    user_id: int
    last_seq: int | None = None
    op: WSClientOp = WSClientOp.SUBSCRIBE


@dataclass(frozen=True)
class SubscribeCommandHandler(BaseCommandHandler[SubscribeCommand, None]):
    manager: ConnectionManager
    chat_repository: ChatRepository
    message_repository: MessageRepository
    message_service: MessageService
    reaction_attach_service: ReactionAttachService

    async def handle(self, command: SubscribeCommand) -> None:
        chat_id = UUID(command.chat_id)
        member = await self.chat_repository.get_member_chat(
            chat_id=chat_id, member_id=command.user_id, with_role=False
        )

        if member is None or member.is_banned:
            command.conn.try_send({
                "type": "ws.error",
                "code": "NOT_CHAT_MEMBER",
                "detail": "You are not a member of this chat"
            })
            return

        await self.manager.subscribe_channel(command.conn, command.chat_id)
        command.conn.try_send({
            "type": "ws.subscribed",
            "chat_id": str(chat_id),
            "payload": {"last_seq": command.last_seq},
        })

        if command.last_seq is not None:
            limit = chat_config.WS_REPLAY_BATCH_SIZE
            last_seq = max(0, command.last_seq)
            messages = await self.message_repository.get_chat_messages_after_seq(
                chat_id=chat_id,
                last_seq=last_seq,
                limit=limit,
            )
            batch = messages[:limit]
            next_last_seq = batch[-1].seq if batch else last_seq
            command.conn.last_seq_by_chat[str(chat_id)] = next_last_seq

            command.conn.try_send(
                {
                    "type": "ws.history",
                    "chat_id": str(chat_id),
                    "payload": {
                        "after_seq": last_seq,
                        "messages": [
                            message.model_dump(mode="json")
                            for message in await self.reaction_attach_service.attach(
                                await self.message_service.attach_download_urls([
                                    MessageDTO.model_validate(item) for item in batch
                                ]),
                                command.user_id,
                            )
                        ],
                        "has_more": len(messages) > limit,
                        "next_last_seq": next_last_seq,
                    },
                },
            )
