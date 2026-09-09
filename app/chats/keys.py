from enum import StrEnum


class ChatIdempotencyScope(StrEnum):
    SEND_MESSAGE = "chats.message.send"
    FORWARD_MESSAGE = "chats.message.forward"


class ReactionKeys:
    @staticmethod
    def reaction_coalesce_pending() -> str:
        return "reactions:coalesce:pending"

    @staticmethod
    def reaction_coalesce_due() -> str:
        return "reactions:coalesce:due"


class ReadReceiptKeys:
    @staticmethod
    def coalesce_pending() -> str:
        return "reads:coalesce:pending"

    @staticmethod
    def coalesce_due() -> str:
        return "reads:coalesce:due"

    @staticmethod
    def coalesce_field(chat_id: str, user_id: int) -> str:
        return f"{chat_id}:{int(user_id)}"

    @staticmethod
    def parse_coalesce_field(field: str) -> tuple[str, int] | None:
        chat_id, sep, user_id = field.rpartition(":")
        if not sep or not chat_id:
            return None
        try:
            return chat_id, int(user_id)
        except ValueError:
            return None
