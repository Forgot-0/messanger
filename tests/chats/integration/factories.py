from typing import Any


def group_chat_payload(
    *,
    name: str = "Integration Group",
    member_ids: list[int] | None = None,
    is_public: bool = False,
    slow_mode_seconds: int = 0,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": "integration",
        "chat_type": "group",
        "member_ids": member_ids if member_ids is not None else [1],
        "is_public": is_public,
        "admin_only": False,
        "slow_mode_seconds": slow_mode_seconds,
        "permissions": {},
    }


def direct_chat_payload(*, peer_user_id: int) -> dict[str, Any]:
    return {
        "name": None,
        "description": None,
        "chat_type": "direct",
        "member_ids": [1, peer_user_id],
        "is_public": False,
        "admin_only": False,
        "slow_mode_seconds": 0,
        "permissions": {},
    }


def send_text_payload(content: str) -> dict[str, Any]:
    return {
        "content": content,
        "reply_to_id": None,
        "message_type": "text",
        "upload_tokens": [],
    }
