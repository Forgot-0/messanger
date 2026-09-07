import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.repositories.profiles import ProfileRepository


@pytest.fixture
async def profile_repository(db_session: AsyncSession, redis_client) -> ProfileRepository:
    return ProfileRepository(session=db_session, redis=redis_client)
