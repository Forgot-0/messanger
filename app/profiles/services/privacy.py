from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.privacy import DEFAULT_VISIBILITY, PrivacyRule, PrivacyVisibility, is_allowed
from app.profiles.repositories.contacts import ContactRepository
from app.profiles.repositories.privacy import ProfilePrivacyRepository


class PhotoHolder(Protocol):
    id: int
    avatars: dict[Any, dict[Any, str]]


@dataclass
class ProfilePrivacyService:
    privacy_repository: ProfilePrivacyRepository
    contact_repository: ContactRepository

    async def allowed_by(
        self, rule: PrivacyRule, viewer_id: int | None, owner_ids: Iterable[int]
    ) -> set[int]:
        owners = {int(owner_id) for owner_id in owner_ids}
        if not owners:
            return set()

        allowed: set[int] = set()
        if viewer_id is not None and viewer_id in owners:
            allowed.add(viewer_id)
            owners.discard(viewer_id)

        if not owners:
            return allowed

        visibility = await self.privacy_repository.visibility_map(rule, owners)
        exceptions = (
            {}
            if viewer_id is None
            else await self.privacy_repository.exceptions_for(rule, viewer_id, owners)
        )

        need_contacts = {
            owner_id
            for owner_id in owners
            if owner_id not in exceptions
            and visibility.get(owner_id, DEFAULT_VISIBILITY) is PrivacyVisibility.CONTACTS
        }
        contacts: set[int] = set()
        if need_contacts and viewer_id is not None:
            contacts = await self.contact_repository.owners_having_contact(viewer_id, need_contacts)

        for owner_id in owners:
            if is_allowed(
                visibility.get(owner_id, DEFAULT_VISIBILITY),
                is_contact=owner_id in contacts,
                exception=exceptions.get(owner_id),
            ):
                allowed.add(owner_id)

        return allowed

    async def hide_photos(
        self, viewer_id: int | None, holders: Iterable[PhotoHolder | None]
    ) -> None:
        targets = [holder for holder in holders if holder is not None and holder.avatars]
        if not targets:
            return

        allowed = await self.allowed_by(
            PrivacyRule.PHOTO, viewer_id, (holder.id for holder in targets)
        )
        for holder in targets:
            if holder.id not in allowed:
                holder.avatars = {}
