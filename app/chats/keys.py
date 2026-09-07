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
