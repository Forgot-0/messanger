from enum import StrEnum


class ChatIdempotencyScope(StrEnum):
    SEND_MESSAGE = "chats.message.send"
    FORWARD_MESSAGE = "chats.message.forward"
    FORWARD_MESSAGES = "chats.message.forward_many"


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


class ChatAvatarKeys:
    @staticmethod
    def upload_slot(upload_token: str) -> str:
        return f"chats:avatar:upload:{upload_token}"


class AttachmentKeys:
    @staticmethod
    def download_url(s3_key: str) -> str:
        return f"attachment:{s3_key}"



class AttachmentStorageKeys:
    @staticmethod
    def media_prefix(chat_id: object, attachment_id: object) -> str:
        return f"media/{chat_id}/{attachment_id}"

    @classmethod
    def preview(cls, chat_id: object, attachment_id: object, size: int, extension: str) -> str:
        return f"{cls.media_prefix(chat_id, attachment_id)}/previews/{size}.{extension}"
