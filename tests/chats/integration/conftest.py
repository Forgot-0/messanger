import json

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models.chat import Chat, ChatType
from app.chats.models.message import Message
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.reaction import MessageReactionRepository
from app.chats.repositories.reads import ReadReceiptRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.livekit_service import LiveKitService
from app.chats.services.messages import MessageService
from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.service import StorageService
from app.core.websocket.keys import WebsocketKeys
from tests.chats.integration.mock import StubLiveKitService

GATEWAY_ID = "gw-test"


@pytest.fixture
def go_online(redis_client: Redis):
    async def _go_online(user_id: int) -> None:
        await redis_client.sadd(
            WebsocketKeys.user_route_key(user_id), f"{GATEWAY_ID}:conn-{user_id}"
        )

    return _go_online


@pytest.fixture
def delivered_frames(redis_client: Redis):
    async def _delivered_frames() -> list[dict]:
        entries = await redis_client.xrange(WebsocketKeys.gateway_stream_key(GATEWAY_ID))
        return [json.loads(fields["event"]) for _entry_id, fields in entries]

    return _delivered_frames


@pytest.fixture
def livekit() -> LiveKitService:
    return StubLiveKitService(url="ws://test", api_key="k", api_secret="s")


@pytest.fixture
def chat_repository(redis_client, db_session: AsyncSession) -> ChatRepository:
    return ChatRepository(redis=redis_client, session=db_session)


@pytest.fixture
def chat_access_service(rbac_manager) -> ChatAccessService:
    return ChatAccessService(rbac_manager=rbac_manager)


@pytest.fixture
def message_repository(db_session: AsyncSession) -> MessageRepository:
    return MessageRepository(session=db_session)


@pytest.fixture
def attachment_repository(db_session: AsyncSession, redis_client) -> AttachmentRepository:
    return AttachmentRepository(session=db_session, redis=redis_client)


@pytest.fixture
def read_repository(db_session: AsyncSession) -> ReadReceiptRepository:
    return ReadReceiptRepository(session=db_session)


@pytest.fixture
def reaction_repository(db_session: AsyncSession) -> MessageReactionRepository:
    return MessageReactionRepository(session=db_session)


@pytest.fixture
def message_service(
    redis_client, chat_access_service: ChatAccessService, mock_storage_service: StorageService
) -> MessageService:
    return MessageService(
        redis=redis_client,
        access_service=chat_access_service,
        storage_service=mock_storage_service
    )

@pytest.fixture
async def group_chat(db_session: AsyncSession, user_jwt: UserJWTData) -> Chat:
    chat = Chat.create(
        created_by=int(user_jwt.id),
        members_ids=[2, 3],
        chat_type=ChatType.GROUP,
        name="Test Group",
        is_public=False,
    )
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


@pytest.fixture
async def public_group_chat(db_session: AsyncSession, user_jwt: UserJWTData) -> Chat:
    chat = Chat.create(
        created_by=int(user_jwt.id),
        members_ids=[2, 3],
        chat_type=ChatType.GROUP,
        name="Public Group",
        is_public=True,
    )
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


@pytest.fixture
async def direct_chat(db_session: AsyncSession, user_jwt: UserJWTData) -> Chat:
    chat = Chat.create(
        created_by=int(user_jwt.id),
        members_ids=[2],
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


@pytest.fixture
def create_group_chat(db_session: AsyncSession, user_jwt: UserJWTData):
    async def _factory(
        members: list[int],
        slow_mode: int = 0,
        admin_only: bool = False,
        is_public: bool = False,
        name: str = "Test Group",
    ) -> Chat:
        chat = Chat.create(
            created_by=int(user_jwt.id),
            members_ids=members,
            chat_type=ChatType.GROUP,
            name=name,
            is_public=is_public,
            slow_mode_seconds=slow_mode,
            admin_only=admin_only,
        )
        db_session.add(chat)
        await db_session.commit()
        await db_session.refresh(chat)
        return chat

    return _factory


@pytest.fixture
def create_message(db_session: AsyncSession):
    async def _factory(
        chat: Chat,
        sender_jwt: UserJWTData,
        content: str | None,
        forward_from: Message | None = None,
    ) -> Message:
        msg = Message.create(
            sender_id=int(sender_jwt.id),
            chat_id=chat.id,
            content=content,
            seq=chat.seq_counter + 1,
            forwarded_from_author_id=forward_from.author_id if forward_from else None,
            forwarded_from_chat_id=forward_from.chat_id if forward_from else None,
            forwarded_from_message_id=forward_from.id if forward_from else None,
        )
        chat.seq_counter += 1
        db_session.add(msg)
        await db_session.commit()
        await db_session.refresh(msg)
        return msg

    return _factory
