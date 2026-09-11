import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.event import BaseEvent
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.config import profile_config
from app.profiles.dtos.contacts import ImportContactsResultDTO, ImportStatus, UserContactDTO
from app.profiles.exceptions import (
    ContactLimitExceededError,
    IdentifierQuotaExceededError,
    ImportBatchTooLargeError,
)
from app.profiles.models.contacts import ContactAdded, ContactSource, IdentifierKind
from app.profiles.repositories.contacts import (
    BlockedUserRepository,
    ContactIdentifierRepository,
    ContactRepository,
    ContactUpsert,
    PendingUpsert,
)
from app.profiles.services.contact_access import check_contact_owner
from app.profiles.services.identifier_hasher import IdentifierHasher

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImportContactEntry:
    email: str
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True)
class ImportContactsCommand(BaseCommand):
    owner_id: int
    entries: list[ImportContactEntry] = field(default_factory=list)

    user_jwt_data: UserJWTData | None = None


@dataclass(frozen=True)
class ImportContactsCommandHandler(
    BaseCommandHandler[ImportContactsCommand, ImportContactsResultDTO]
):
    session: AsyncSession
    contact_repository: ContactRepository
    identifier_repository: ContactIdentifierRepository
    blocked_repository: BlockedUserRepository
    hasher: IdentifierHasher
    rbac_manager: RBACManagerInterface
    event_bus: BaseEventBus

    async def handle(self, command: ImportContactsCommand) -> ImportContactsResultDTO:
        check_contact_owner(self.rbac_manager, command.owner_id, command.user_jwt_data)

        if len(command.entries) > profile_config.CONTACTS_IMPORT_MAX_BATCH:
            raise ImportBatchTooLargeError(
                limit=profile_config.CONTACTS_IMPORT_MAX_BATCH, current=len(command.entries)
            )

        by_hash, invalid = self._hash_entries(command.entries)

        if not await self.identifier_repository.consume_quota(command.owner_id, len(by_hash)):
            raise IdentifierQuotaExceededError(limit=profile_config.CONTACTS_NEW_IDENTIFIERS_PER_DAY)

        resolved = await self.identifier_repository.resolve(list(by_hash))
        matched, pending = await self._split_by_registration(command.owner_id, by_hash, resolved)

        await self._check_limit(command.owner_id, len(matched))

        inserted = await self.contact_repository.upsert_many(
            command.owner_id,
            [
                ContactUpsert(
                    contact_id=user_id,
                    source=ContactSource.IMPORT,
                    first_name=entry.first_name,
                    last_name=entry.last_name,
                )
                for user_id, entry in matched.items()
            ],
        )
        await self.identifier_repository.upsert_pending_many(command.owner_id, pending)

        reverse = await self.contact_repository.find_reverse_owners(
            command.owner_id, list(matched)
        )
        await self.contact_repository.set_mutual(command.owner_id, sorted(reverse))

        events: list[BaseEvent] = [
            ContactAdded(
                owner_id=command.owner_id,
                contact_id=contact_id,
                source=int(ContactSource.IMPORT),
                is_mutual=contact_id in reverse,
            )
            for contact_id in sorted(inserted)
        ]
        await self.event_bus.publish(events)
        await self.session.commit()

        contacts = await self.contact_repository.get_many(command.owner_id, sorted(matched))

        logger.info(
            "Contacts imported",
            extra={
                "owner_id": command.owner_id,
                "accepted": len(command.entries),
                "matched": len(matched),
                "pending": len(pending),
                "invalid": invalid,
            },
        )

        return ImportContactsResultDTO(
            status=ImportStatus.DONE,
            accepted=len(command.entries),
            matched=len(matched),
            pending=len(pending),
            invalid=invalid,
            contacts=[UserContactDTO.model_validate(contact) for contact in contacts],
        )

    def _hash_entries(
        self, entries: list[ImportContactEntry]
    ) -> tuple[dict[bytes, ImportContactEntry], int]:
        """Хеширует и дедуплицирует батч, считая нераспознанные адреса."""
        by_hash: dict[bytes, ImportContactEntry] = {}
        invalid = 0

        for entry in entries:
            identifier_hash = self.hasher.hash(IdentifierKind.EMAIL, entry.email)

            if identifier_hash is None:
                invalid += 1
                continue

            by_hash.setdefault(identifier_hash, entry)

        return by_hash, invalid

    async def _split_by_registration(
        self,
        owner_id: int,
        by_hash: dict[bytes, ImportContactEntry],
        resolved: dict[bytes, int],
    ) -> tuple[dict[int, ImportContactEntry], list[PendingUpsert]]:
        """Делит батч на найденных пользователей и тех, кого ещё нет.

        Себя и заблокированных в контакты не берём.
        """
        blocked = await self.blocked_repository.get_block_list(owner_id)
        matched: dict[int, ImportContactEntry] = {}
        pending: list[PendingUpsert] = []

        for identifier_hash, entry in by_hash.items():
            user_id = resolved.get(identifier_hash)

            if user_id is None:
                pending.append(
                    PendingUpsert(
                        identifier_hash=identifier_hash,
                        first_name=entry.first_name,
                        last_name=entry.last_name,
                    )
                )
                continue

            if user_id == owner_id or user_id in blocked:
                continue

            matched.setdefault(user_id, entry)

        return matched, pending

    async def _check_limit(self, owner_id: int, incoming: int) -> None:
        if incoming == 0:
            return

        current = await self.contact_repository.count(owner_id)
        if current + incoming > profile_config.MAX_CONTACTS_PER_USER:
            raise ContactLimitExceededError(limit=profile_config.MAX_CONTACTS_PER_USER)
