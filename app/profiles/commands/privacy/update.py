import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.privacy import PrivacyRule, PrivacyVisibility
from app.profiles.dtos.privacy import PrivacySettingsDTO
from app.profiles.repositories.privacy import ProfilePrivacyRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PrivacyExceptionsUpdate:
    allow: list[int] = field(default_factory=list)
    deny: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class UpdatePrivacySettingsCommand(BaseCommand):
    user_id: int
    rules: dict[PrivacyRule, PrivacyVisibility] = field(default_factory=dict)
    exceptions: dict[PrivacyRule, PrivacyExceptionsUpdate] = field(default_factory=dict)


@dataclass(frozen=True)
class UpdatePrivacySettingsCommandHandler(
    BaseCommandHandler[UpdatePrivacySettingsCommand, PrivacySettingsDTO]
):
    session: AsyncSession
    privacy_repository: ProfilePrivacyRepository
    event_bus: BaseEventBus

    async def handle(self, command: UpdatePrivacySettingsCommand) -> PrivacySettingsDTO:
        privacy = await self.privacy_repository.get_or_create(command.user_id)

        for rule, visibility in command.rules.items():
            privacy.set_rule(rule, visibility)

        for rule, update in command.exceptions.items():
            privacy.replace_exceptions(rule, update.allow, update.deny)

        privacy.register_updated()
        await self.event_bus.publish(privacy.pull_events())
        await self.session.commit()

        logger.info(
            "Privacy settings updated",
            extra={
                "user_id": command.user_id,
                "rules": [rule.value for rule in command.rules],
                "exceptions": [rule.value for rule in command.exceptions],
            },
        )

        return PrivacySettingsDTO(
            rules=privacy.rules_snapshot(),  # type: ignore[arg-type]
            exceptions=privacy.exceptions_snapshot(),  # type: ignore[arg-type]
        )
