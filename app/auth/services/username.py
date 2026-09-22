import re
import secrets
from dataclasses import dataclass
from typing import ClassVar
from uuid import uuid4

from app.auth.repositories.user import UserRepository

MIN_LENGTH = 4
MAX_LENGTH = 100

SUFFIX_LENGTH = 7
BASE_MAX_LENGTH = MAX_LENGTH - SUFFIX_LENGTH

FALLBACK_BASE = "user"

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_TRANSLIT = {
    **_CYRILLIC,
    **{letter.upper(): latin.capitalize() for letter, latin in _CYRILLIC.items() if latin},
}

_DISALLOWED = re.compile(r"[^a-zA-Z0-9 ,.'-]")
_SPACES = re.compile(r"\s+")
_TRIM = " ,.'-"


def normalize_username(raw: str | None) -> str:
    if not raw:
        return ""

    transliterated = "".join(_TRANSLIT.get(char, char) for char in raw)
    cleaned = _DISALLOWED.sub(" ", transliterated)

    return _SPACES.sub(" ", cleaned).strip(_TRIM)[:BASE_MAX_LENGTH].strip(_TRIM)


@dataclass
class UsernameGenerator:
    user_repository: UserRepository
    attempts: ClassVar[int] = 5

    async def generate(self, preferred: str | None, email: str) -> str:
        base = (
            normalize_username(preferred)
            or normalize_username(email.split("@", 1)[0])
            or FALLBACK_BASE
        )

        if len(base) >= MIN_LENGTH and await self._is_free(base):
            return base

        for _ in range(self.attempts):
            candidate = f"{base}-{secrets.token_hex(3)}"
            if await self._is_free(candidate):
                return candidate

        return f"{base}-{uuid4().hex}"[:MAX_LENGTH]

    async def _is_free(self, username: str) -> bool:
        return not await self.user_repository.exists_username(username)
