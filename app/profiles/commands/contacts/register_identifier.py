import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.event import BaseEvent
from app.core.events.service import BaseEventBus
from app.profiles.config import profile_config
from app.profiles.models.contacts import ContactAdded, ContactSource, IdentifierKind, PendingContact
from app.profiles.repositories.contacts import (
    ContactIdentifierRepository,
    ContactRepository,
    ContactUpsert,
)
from app.profiles.services.identifier_hasher import IdentifierHasher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegisterUserIdentifierCommand(BaseCommand):
    user_id: int
    email: str


@dataclass(frozen=True)
class RegisterUserIdentifierCommandHandler(
    BaseCommandHandler[RegisterUserIdentifierCommand, int]
):
    session: AsyncSession
    identifier_repository: ContactIdentifierRepository
    contact_repository: ContactRepository
    hasher: IdentifierHasher
    event_bus: BaseEventBus

    async def handle(self, command: RegisterUserIdentifierCommand) -> int:
        identifier_hash = self.hasher.hash(IdentifierKind.EMAIL, command.email)

        if identifier_hash is None:
            logger.warning(
                "User identifier is not normalizable, skipping",
                extra={"user_id": command.user_id},
            )
            return 0

        await self.identifier_repository.upsert(
            identifier_hash, IdentifierKind.EMAIL, command.user_id
        )
        await self.session.commit()

        return await self._resolve_pending(identifier_hash, command.user_id)

    async def _resolve_pending(self, identifier_hash: bytes, user_id: int) -> int:
        """Ожидающих может быть десятки тысяч, поэтому идём курсором по
        owner_id батчами и коммитим каждый батч отдельно."""
        resolved = 0
        events_left = profile_config.PENDING_RESOLVE_MAX_EVENTS
        after_owner_id: int | None = None

        while True:
            batch = await self.identifier_repository.fetch_pending_batch(
                identifier_hash,
                limit=profile_config.PENDING_RESOLVE_BATCH_SIZE,
                after_owner_id=after_owner_id,
            )
            if not batch:
                break

            events_left -= await self._apply_batch(batch, user_id, events_left)
            resolved += len(batch)
            after_owner_id = batch[-1].owner_id

        if resolved:
            logger.info(
                "Pending contacts resolved",
                extra={"user_id": user_id, "resolved": resolved},
            )

        return resolved

    async def _apply_batch(
        self, batch: list[PendingContact], user_id: int, events_left: int
    ) -> int:
        """Батч ожидающих разбирается четырьмя запросами: апсерт, проверка
        встречных строк, простановка взаимности, удаление pending."""
        events_limit = max(events_left, 0)
        waiting = [pending for pending in batch if pending.owner_id != user_id]

        inserted_pairs = await self.contact_repository.upsert_many_pairs(
            [
                (
                    pending.owner_id,
                    ContactUpsert(
                        contact_id=user_id,
                        source=ContactSource.IMPORT,
                        first_name=pending.first_name,
                        last_name=pending.last_name,
                    ),
                )
                for pending in waiting
            ]
        )

        owner_ids = [pending.owner_id for pending in waiting]
        mutual_owners = await self.contact_repository.find_forward_contacts(user_id, owner_ids)
        await self.contact_repository.set_mutual_pairs(
            [(owner_id, user_id) for owner_id in sorted(mutual_owners)]
        )

        events: list[BaseEvent] = [
            ContactAdded(
                owner_id=owner_id,
                contact_id=contact_id,
                source=int(ContactSource.IMPORT),
                is_mutual=owner_id in mutual_owners,
            )
            for owner_id, contact_id in sorted(inserted_pairs)[:events_limit]
        ]

        await self.identifier_repository.delete_pending(
            batch[0].identifier_hash, [pending.owner_id for pending in batch]
        )
        await self.event_bus.publish(events)
        await self.session.commit()

        return len(events)
