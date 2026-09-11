import pytest
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.repositories.contacts import (
    BlockedUserRepository,
    ContactIdentifierRepository,
    ContactRepository,
)
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.identifier_hasher import IdentifierHasher


@pytest.fixture
async def profile_repository(db_session: AsyncSession, redis_client) -> ProfileRepository:
    return ProfileRepository(session=db_session, redis=redis_client)


@pytest.fixture
async def contact_repository(db_session: AsyncSession) -> ContactRepository:
    return ContactRepository(session=db_session)


@pytest.fixture
async def identifier_repository(
    db_session: AsyncSession, redis_client: Redis
) -> ContactIdentifierRepository:
    return ContactIdentifierRepository(session=db_session, redis=redis_client)


@pytest.fixture
async def blocked_repository(
    db_session: AsyncSession, redis_client: Redis
) -> BlockedUserRepository:
    return BlockedUserRepository(session=db_session, redis=redis_client)


@pytest.fixture
async def identifier_hasher(di_container: AsyncContainer) -> IdentifierHasher:
    return await di_container.get(IdentifierHasher)
