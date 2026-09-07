import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.models.profile import Profile


@pytest.fixture
async def persisted_profile_contact(db_session: AsyncSession, user_jwt):
    async def _make(contacts: list[tuple[str, str]]):
        profile = Profile.create(
            user_id=int(user_jwt.id),
            username=user_jwt.username,
            specialization="backend",
            display_name="test_name",
            bio="Python Developer",
            skills={"python", "sql", "fastapi"},
        )

        for contact in contacts:
            profile.add_contact(contact[0], contact[1])

        db_session.add(profile)
        await db_session.commit()
        await db_session.refresh(profile)
        return profile
    return _make


@pytest.fixture
async def persisted_profile(db_session: AsyncSession, user_jwt) -> Profile:
    profile = Profile.create(
        user_id=int(user_jwt.id),
        username=user_jwt.username,
        specialization="backend",
        display_name="test_name",
        bio="Python Developer",
        skills={"python", "sql", "fastapi"},
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)
    return profile

