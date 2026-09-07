import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models.profile import ChatUserProfile
from app.core.services.auth.dto import UserJWTData


@pytest.fixture
async def create_profile(db_session: AsyncSession):
    async def _headers(user_jwt: UserJWTData) -> None:
        profile = ChatUserProfile.create(
            user_id=int(user_jwt.id),
            username=user_jwt.username
        )
        db_session.add(profile)
        await db_session.commit()

    return _headers
