import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.profiles.commands.contacts.import_batch import (
    ImportContactEntry,
    ImportContactsCommand,
    ImportContactsCommandHandler,
)
from app.profiles.config import profile_config
from app.profiles.exceptions import IdentifierQuotaExceededError, ImportBatchTooLargeError
from app.profiles.models.contacts import ContactAdded, ContactSource, IdentifierKind
from app.profiles.repositories.contacts import ContactRepository

OWNER_ID = 1
FRIEND_ID = 8901
OTHER_ID = 8902


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestImportContactsCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> ImportContactsCommandHandler:
        return await request_container.get(ImportContactsCommandHandler)

    async def test_known_email_becomes_a_contact(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        register_identifier,
        contact_repository: ContactRepository,
    ) -> None:
        await make_profile(FRIEND_ID, "friend", "Friend")
        await register_identifier(FRIEND_ID, "friend@example.com")

        result = await handler.handle(
            ImportContactsCommand(
                owner_id=OWNER_ID,
                entries=[ImportContactEntry(email="Friend@Example.com", first_name="Вася")],
                user_jwt_data=user_jwt,
            )
        )

        assert result.matched == 1
        assert result.pending == 0
        assert result.invalid == 0
        assert result.contacts[0].first_name == "Вася"
        assert result.contacts[0].profile is not None

        stored = await contact_repository.get(OWNER_ID, FRIEND_ID)
        assert stored is not None
        assert stored.source is ContactSource.IMPORT

    async def test_unknown_email_is_parked_in_pending(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        identifier_repository,
        identifier_hasher,
    ) -> None:
        result = await handler.handle(
            ImportContactsCommand(
                owner_id=OWNER_ID,
                entries=[ImportContactEntry(email="nobody@example.com", first_name="Кто-то")],
                user_jwt_data=user_jwt,
            )
        )

        assert result.matched == 0
        assert result.pending == 1

        identifier_hash = identifier_hasher.hash(IdentifierKind.EMAIL, "nobody@example.com")
        waiting = await identifier_repository.fetch_pending_batch(identifier_hash, limit=10)
        assert [row.owner_id for row in waiting] == [OWNER_ID]

    async def test_broken_email_is_counted_as_invalid(
        self, handler: ImportContactsCommandHandler, user_jwt: UserJWTData
    ) -> None:
        result = await handler.handle(
            ImportContactsCommand(
                owner_id=OWNER_ID,
                entries=[ImportContactEntry(email="не почта")],
                user_jwt_data=user_jwt,
            )
        )

        assert result.invalid == 1
        assert result.matched == 0
        assert result.pending == 0

    async def test_duplicates_inside_one_batch_are_collapsed(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        register_identifier,
        contact_repository: ContactRepository,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await register_identifier(FRIEND_ID, "friend@example.com")

        result = await handler.handle(
            ImportContactsCommand(
                owner_id=OWNER_ID,
                entries=[
                    ImportContactEntry(email="friend@example.com"),
                    ImportContactEntry(email="FRIEND@example.com"),
                ],
                user_jwt_data=user_jwt,
            )
        )

        assert result.matched == 1
        assert await contact_repository.count(OWNER_ID) == 1

    async def test_self_and_blocked_are_skipped(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        register_identifier,
        make_block,
        contact_repository: ContactRepository,
    ) -> None:
        await make_profile(OWNER_ID, "me")
        await make_profile(OTHER_ID, "blocked_one")
        await register_identifier(OWNER_ID, "me@example.com")
        await register_identifier(OTHER_ID, "blocked@example.com")
        await make_block(OWNER_ID, OTHER_ID)

        result = await handler.handle(
            ImportContactsCommand(
                owner_id=OWNER_ID,
                entries=[
                    ImportContactEntry(email="me@example.com"),
                    ImportContactEntry(email="blocked@example.com"),
                ],
                user_jwt_data=user_jwt,
            )
        )

        assert result.matched == 0
        assert await contact_repository.count(OWNER_ID) == 0

    async def test_repeated_import_publishes_events_once(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        register_identifier,
        mock_event_bus,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await register_identifier(FRIEND_ID, "friend@example.com")
        command = ImportContactsCommand(
            owner_id=OWNER_ID,
            entries=[ImportContactEntry(email="friend@example.com")],
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)
        await handler.handle(command)

        assert len(mock_event_bus.of_type(ContactAdded)) == 1

    async def test_mutual_is_set_when_the_other_side_already_added_me(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        register_identifier,
        make_contact,
        contact_repository: ContactRepository,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await register_identifier(FRIEND_ID, "friend@example.com")
        await make_contact(FRIEND_ID, OWNER_ID)

        await handler.handle(
            ImportContactsCommand(
                owner_id=OWNER_ID,
                entries=[ImportContactEntry(email="friend@example.com")],
                user_jwt_data=user_jwt,
            )
        )

        mine = await contact_repository.get(OWNER_ID, FRIEND_ID)
        theirs = await contact_repository.get(FRIEND_ID, OWNER_ID)
        assert mine is not None and mine.is_mutual is True
        assert theirs is not None and theirs.is_mutual is True

    async def test_batch_over_the_limit_is_rejected(
        self, handler: ImportContactsCommandHandler, user_jwt: UserJWTData
    ) -> None:
        entries = [
            ImportContactEntry(email=f"user{i}@example.com")
            for i in range(profile_config.CONTACTS_IMPORT_MAX_BATCH + 1)
        ]

        with pytest.raises(ImportBatchTooLargeError):
            await handler.handle(
                ImportContactsCommand(
                    owner_id=OWNER_ID, entries=entries, user_jwt_data=user_jwt
                )
            )

    async def test_daily_identifier_quota_is_enforced(
        self,
        handler: ImportContactsCommandHandler,
        user_jwt: UserJWTData,
        identifier_repository,
    ) -> None:
        await identifier_repository.consume_quota(
            OWNER_ID, profile_config.CONTACTS_NEW_IDENTIFIERS_PER_DAY
        )

        with pytest.raises(IdentifierQuotaExceededError):
            await handler.handle(
                ImportContactsCommand(
                    owner_id=OWNER_ID,
                    entries=[ImportContactEntry(email="one-more@example.com")],
                    user_jwt_data=user_jwt,
                )
            )
