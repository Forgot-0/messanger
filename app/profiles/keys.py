from enum import StrEnum


class ProfileIdempotencyScope(StrEnum):
    IMPORT_CONTACTS = "profiles.contacts.import"


class ContactKeys:
    """Единственное место, где собираются ключи Redis модуля profiles."""

    _NAMESPACE = "profiles:v1:"

    @staticmethod
    def block_list(owner_id: int) -> str:
        return f"{ContactKeys._NAMESPACE}blocklist:{int(owner_id)}"

    @staticmethod
    def identifier_quota(owner_id: int, day: str) -> str:
        return f"{ContactKeys._NAMESPACE}identifiers:quota:{int(owner_id)}:{day}"


class ContactWSEventType(StrEnum):
    IMPORT_COMPLETED = "contacts_import_completed"
