from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.models.contacts import BlockedUser, ContactSource, IdentifierKind, UserContact
from app.profiles.models.profile import Profile
from app.profiles.repositories.contacts import ContactIdentifierRepository, PendingUpsert
from app.profiles.services.identifier_hasher import IdentifierHasher


@pytest.fixture
async def persisted_profile_links(db_session: AsyncSession, user_jwt):
    async def _make(links: list[tuple[str, str]]):
        profile = Profile.create(
            user_id=int(user_jwt.id),
            username=user_jwt.username,
            specialization="backend",
            display_name="test_name",
            bio="Python Developer",
            skills={"python", "sql", "fastapi"},
        )

        for provider, contact in links:
            profile.add_link(provider, contact)

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


@pytest.fixture
async def make_profile(db_session: AsyncSession):
    async def _make(user_id: int, username: str, display_name: str | None = None) -> Profile:
        profile = Profile.create(
            user_id=user_id,
            username=username,
            specialization=None,
            display_name=display_name,
            bio=None,
            skills=set(),
        )
        db_session.add(profile)
        await db_session.commit()
        await db_session.refresh(profile)
        return profile

    return _make


@pytest.fixture
async def make_contact(db_session: AsyncSession):
    async def _make(
        owner_id: int,
        contact_id: int,
        source: ContactSource = ContactSource.MANUAL,
        first_name: str | None = None,
        is_mutual: bool = False,
        updated_at: datetime | None = None,
    ) -> UserContact:
        contact = UserContact.create(
            owner_id=owner_id,
            contact_id=contact_id,
            source=source,
            first_name=first_name,
            is_mutual=is_mutual,
        )
        contact.pull_events()

        if updated_at is not None:
            contact.created_at = updated_at
            contact.updated_at = updated_at

        db_session.add(contact)
        await db_session.commit()
        return contact

    return _make


@pytest.fixture
async def make_block(db_session: AsyncSession):
    async def _make(owner_id: int, target_id: int) -> BlockedUser:
        blocked = BlockedUser.create(owner_id=owner_id, target_id=target_id)
        blocked.pull_events()
        db_session.add(blocked)
        await db_session.commit()
        return blocked

    return _make


@pytest.fixture
async def register_identifier(
    identifier_repository: ContactIdentifierRepository,
    identifier_hasher: IdentifierHasher,
    db_session: AsyncSession,
):
    """Пишет user_identifiers так же, как это делает консьюмер регистрации."""

    async def _register(user_id: int, email: str) -> bytes:
        identifier_hash = identifier_hasher.hash(IdentifierKind.EMAIL, email)
        assert identifier_hash is not None

        await identifier_repository.upsert(identifier_hash, IdentifierKind.EMAIL, user_id)
        await db_session.commit()
        return identifier_hash

    return _register


@pytest.fixture
async def make_pending(
    identifier_repository: ContactIdentifierRepository,
    identifier_hasher: IdentifierHasher,
    db_session: AsyncSession,
):
    async def _make(owner_id: int, email: str, first_name: str | None = None) -> bytes:
        identifier_hash = identifier_hasher.hash(IdentifierKind.EMAIL, email)
        assert identifier_hash is not None

        await identifier_repository.upsert_pending_many(
            owner_id, [PendingUpsert(identifier_hash=identifier_hash, first_name=first_name)]
        )
        await db_session.commit()
        return identifier_hash

    return _make
