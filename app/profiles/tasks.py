import logging
from dataclasses import dataclass
from typing import Any

from dishka.integrations.taskiq import FromDishka, inject
from taskiq import AsyncBroker

from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask
from app.core.utils import now_utc
from app.core.websocket.dtos import DeliveryData, DeliveryDTO
from app.core.websocket.manager import ConnectionManager
from app.profiles.commands.contacts.import_batch import ImportContactEntry, ImportContactsCommand
from app.profiles.commands.profiles.proccess_avatar import ProccessAvatarCommand
from app.profiles.dtos.contacts import ImportCompletedPayload
from app.profiles.keys import ContactWSEventType

logger = logging.getLogger(__name__)


def register_profiles_tasks(broker: AsyncBroker) -> None:
    broker.register_task(
        AvatarUploadTask.run, AvatarUploadTask.get_name()
    )
    broker.register_task(
        ContactsImportTask.run, ContactsImportTask.get_name()
    )


@dataclass
class AvatarUploadTask(BaseTask):
    __task_name__ = "avatar.resize"

    @staticmethod
    @inject
    async def run(
        user_id: int,
        key_base: str,
        mediator: FromDishka[BaseMediator],
    ) -> None:
        await mediator.handle_command(
            ProccessAvatarCommand(
                user_id=user_id,
                file_key=key_base
            )
        )


@dataclass
class ContactsImportTask(BaseTask):
    """Долгий импорт адресной книги: HTTP уже ответил 202, результат
    доезжает до клиента WS-событием."""

    __task_name__ = "profiles.contacts.import"

    @staticmethod
    @inject
    async def run(
        owner_id: int,
        entries: list[dict[str, Any]],
        mediator: FromDishka[BaseMediator],
        connection_manager: FromDishka[ConnectionManager],
    ) -> None:
        result = await mediator.handle_command(
            ImportContactsCommand(
                owner_id=owner_id,
                entries=[
                    ImportContactEntry(
                        email=entry["email"],
                        first_name=entry.get("first_name"),
                        last_name=entry.get("last_name"),
                    )
                    for entry in entries
                ],
            )
        )

        payload = ImportCompletedPayload(
            owner_id=owner_id,
            matched=result.matched,
            pending=result.pending,
            invalid=result.invalid,
            accepted=result.accepted,
        )

        await connection_manager.send_user_payload(
            DeliveryDTO(
                type=ContactWSEventType.IMPORT_COMPLETED,
                channel=str(owner_id),
                payload=payload.model_dump(),
                delivery=DeliveryData(require_subscription=False, recipients=[owner_id]),
                ts=now_utc().isoformat(),
            )
        )

        logger.info(
            "Contacts import finished",
            extra={"owner_id": owner_id, "matched": result.matched, "pending": result.pending},
        )
