import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import ClassVar

from app.profiles.config import profile_config
from app.profiles.exceptions import IdentifierPepperNotConfiguredError
from app.profiles.models.contacts import IdentifierKind


@dataclass(frozen=True, slots=True)
class IdentifierHasher:
    """Нормализация и слепое хеширование идентификаторов адресной книги.

    Сырые email и телефоны в базу не попадают: хранится только
    hmac_sha256(pepper, normalized). Из-за этого поиск по сырому значению
    невозможен в принципе — только точное совпадение хешей.
    """

    EMAIL_RE: ClassVar[re.Pattern[str]] = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
    NOT_DIGITS_RE: ClassVar[re.Pattern[str]] = re.compile(r"\D+")

    pepper: str

    def normalize_email(self, raw: str | None) -> str | None:
        if not raw:
            return None

        candidate = raw.strip().lower()
        if len(candidate) > profile_config.MAX_LEN_EMAIL or not self.EMAIL_RE.match(candidate):
            return None

        return candidate

    def normalize_phone(self, raw: str | None) -> str | None:
        """E.164 без справочника кодов стран: только цифры и ведущий плюс.

        Телефоны как идентификатор пока не заводятся, но схема обязана принять
        их позже без миграции контактов.
        """
        if not raw:
            return None

        digits = self.NOT_DIGITS_RE.sub("", raw)
        too_short = len(digits) < profile_config.MIN_PHONE_DIGITS
        too_long = len(digits) > profile_config.MAX_PHONE_DIGITS

        if too_short or too_long or digits.startswith("0"):
            return None

        return f"+{digits}"

    def normalize(self, kind: IdentifierKind, raw: str | None) -> str | None:
        if kind is IdentifierKind.EMAIL:
            return self.normalize_email(raw)
        return self.normalize_phone(raw)

    def hash_normalized(self, normalized: str) -> bytes:
        if not self.pepper.strip():
            raise IdentifierPepperNotConfiguredError

        return hmac.new(
            self.pepper.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
        ).digest()

    def hash(self, kind: IdentifierKind, raw: str | None) -> bytes | None:
        normalized = self.normalize(kind, raw)
        if normalized is None:
            return None

        return self.hash_normalized(normalized)
