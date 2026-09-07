from fastapi import APIRouter

from app.chats.routes.v1 import attachments, calls, chats, members, messages, reactions, ws

router_v1 = APIRouter()

router_v1.include_router(chats.router, prefix="/chats", tags=["chats"])
router_v1.include_router(members.router, prefix="/chats/{chat_id}/members", tags=["chat-members"])
router_v1.include_router(messages.router, prefix="/chats/{chat_id}/messages", tags=["chat-messages"])
router_v1.include_router(attachments.router, prefix="/chats/{chat_id}", tags=["chat-attachments"])
router_v1.include_router(calls.router, prefix="/chats/{chat_id}/calls", tags=["chat-calls"])
router_v1.include_router(
    reactions.router,
    prefix="/chats/{chat_id}/messages/{message_id}/reactions",
    tags=["chat-reactions"],
)
router_v1.include_router(ws.router, prefix="/chats", tags=["chats-ws"])
