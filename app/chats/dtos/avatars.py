from collections.abc import Mapping
from typing import Any

CHAT_AVATAR_SIZE = 64

AVATAR_FORMAT_PREFERENCE: tuple[str, ...] = ("jpg", "webp", "avif")


def _normalize_size_key(key: Any) -> str:
    return str(key).strip()


def pick_avatar_key(
    avatars: Mapping[Any, Any] | None,
    size: int = CHAT_AVATAR_SIZE,
    formats: tuple[str, ...] = AVATAR_FORMAT_PREFERENCE,
) -> str | None:
    if not avatars or not isinstance(avatars, Mapping):
        return None

    by_size: dict[str, Any] = {
        _normalize_size_key(raw_size): value for raw_size, value in avatars.items()
    }

    candidates: list[str] = [str(size)]
    numeric_sizes: list[int] = []
    for raw_size in by_size:
        try:
            numeric_sizes.append(int(raw_size))
        except (TypeError, ValueError):
            continue

    for fallback in sorted(numeric_sizes, key=lambda s: (abs(s - size), -s)):
        if str(fallback) not in candidates:
            candidates.append(str(fallback))

    for size_key in candidates:
        variants = by_size.get(size_key)
        if not isinstance(variants, Mapping):
            continue
        for fmt in formats:
            value = variants.get(fmt)
            if isinstance(value, str) and value:
                return value

    return None
