from enum import StrEnum


class PrivacyRule(StrEnum):
    """Оси приватности. Значение = имя колонки в `profile_privacy`."""

    LAST_SEEN = "last_seen"
    PHOTO = "photo"
    MESSAGES = "messages"
    GROUP_INVITES = "group_invites"
    CALLS = "calls"


class PrivacyVisibility(StrEnum):
    EVERYBODY = "everybody"
    CONTACTS = "contacts"
    NOBODY = "nobody"


DEFAULT_VISIBILITY = PrivacyVisibility.EVERYBODY


def is_allowed(
    visibility: PrivacyVisibility,
    *,
    is_self: bool = False,
    is_contact: bool = False,
    exception: bool | None = None,
) -> bool:
    if is_self:
        return True

    if exception is not None:
        return exception

    if visibility is PrivacyVisibility.EVERYBODY:
        return True

    if visibility is PrivacyVisibility.CONTACTS:
        return is_contact

    return False
