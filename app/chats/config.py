from app.core.configs.base import BaseConfig


class ChatConfig(BaseConfig):
    MAX_MEMBERS: int = 1_000
    MAX_GROUP_MEMBERS: int = 500
    MAX_SUPERGROUP_MEMBERS: int = 1_000_000
    MAX_CHANNEL_SUBSCRIBERS: int = 10_000_000
    MAX_MESSAGE_LENGTH: int = 4_096

    MAX_DISTINCT_REACTIONS_PER_MESSAGE: int = 20
    MAX_REACTIONS_PER_USER_PER_MESSAGE: int = 3
    MAX_BULK_ADD_MEMBERS: int = 100

    FAN_OUT_WRITE_THRESHOLD: int = 500

    MAX_SLOW_MODE_SECONDS: int = 86_400
    CHAT_STAFF_MIN_ROLE_LEVEL: int = 80
    CHAT_EDITOR_MIN_ROLE_LEVEL: int = 80

    WS_ACTIVE_SUBSCRIBER_SCAN_COUNT: int = 1_000
    WS_REPLAY_BATCH_SIZE: int = 50
    WS_MAX_CLIENT_FRAME_BYTES: int = 65_536
    RATE_LIMIT_MESSAGES_PER_SECOND: int = 10

    CHAT_TOPIC: str = "chats"
    PROFILE_TOPIC: str= "profiles"

    CHAT_OFFLINE_DELIVERY_TOPIC: str = "chats.offline-delivery"

    DELIVERY_ROUTER_GROUP_ID: str = "delivery-router"
    DELIVERY_ROUTER_MEMBER_BATCH_SIZE: int = 2_000
    DELIVERY_ROUTER_ROUTE_LOOKUP_BATCH_SIZE: int = 500
    DELIVERY_ROUTER_ACTIVE_SUBSCRIBER_SCAN_BATCH_SIZE: int = 1_000

    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    ROOM_TOKEN_TTL: int = 3_600
    ROOM_MAX_PARTICIPANTS: int = 100

    ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset({
        "image/jpeg", "image/png", "image/gif",
        "image/webp", "image/heic", "image/heif",
    })
    ALLOWED_VIDEO_MIMES: frozenset[str] = frozenset({
        "video/mp4", "video/webm",
        "video/quicktime", "video/x-msvideo",
    })
    ALLOWED_FILE_MIMES: frozenset[str] = frozenset({
        "application/pdf",
        "application/zip", "application/x-zip-compressed",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain", "text/csv",
    })

    ALLOWED_VOICE_MIMES: frozenset[str] = frozenset({
        "audio/ogg", "audio/opus",
        "audio/mpeg", "audio/mp4", "audio/aac", "audio/webm",
        "audio/x-m4a",
    })

    ALLOWED_VIDEO_NOTE_MIMES: frozenset[str] = frozenset({
        "video/mp4", "video/webm", "video/quicktime",
    })
    ALL_ALLOWED_MIMES: frozenset[str] = (
        ALLOWED_IMAGE_MIMES
        | ALLOWED_VIDEO_MIMES
        | ALLOWED_FILE_MIMES
        | ALLOWED_VOICE_MIMES
        | ALLOWED_VIDEO_NOTE_MIMES
    )

    MAX_MEDIA_PER_MESSAGE: int = 10
    MAX_FILES_PER_MESSAGE: int = 1

    MAX_FILE_SIZE: int = 100 * 1024 * 1024
    MAX_MEDIA_SIZE: int = 50 * 1024 * 1024

    MAX_VOICE_SIZE: int = 20 * 1024 * 1024
    MAX_VIDEO_NOTE_SIZE: int = 40 * 1024 * 1024
    MAX_VIDEO_NOTE_FPS: int = 60
    MAX_VOICE_DURATION_SECONDS: int = 600
    MAX_VIDEO_NOTE_DURATION_SECONDS: int = 60
    MAX_VIDEO_NOTE_RESOLUTION_PX: int = 640

    DOWNLOAD_URL_TTL: int = 300
    ATTACHMENT_UPLOAD_TOKEN_TTL: int = 3_600

    ATTACHMENT_BUCKET: str = "chat-attachments"
    ATTACHMENT_BUCKET_PENDING: str = "chat-pending-attachments"
    AVATAR_BUCKET: str = "profiles"

    RATE_LIMIT_REACTIONS_PER_SECOND: int = 10
    MAX_REACTION_LENGTH: int = 32

    REACTION_RECENT_USERS_LIMIT: int = 3
    REACTIONS_INCLUDE_RECENT_USERS: bool = True

    REACTIONS_COALESCE_WINDOW_MS: int = 500
    REACTIONS_COALESCE_TICK_MS: int = 100
    REACTIONS_COALESCE_MAX_KEYS_PER_TICK: int = 500
    REACTIONS_COALESCE_LOCK_TTL_MS: int = 5_000
    DEFAULT_REACTIONS: tuple[str, ...] = (
        "👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱",
        "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊️", "🤡",
        "🥱", "🥴", "😍", "🐳", "❤️‍🔥", "🌚", "🌭", "💯", "🤣", "⚡️",
        "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈",
        "😴", "😭", "🤓", "👻", "👩‍💻", "👀", "🎃", "🙈", "😇", "😨",
        "🤝", "✍️", "🤗", "🫡", "🎅", "🎄", "☃️", "💅", "🤪", "🗿",
        "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂️",
        "🤷", "🤷‍♀️", "😡",
    )

    PROFILE_PROJECTION_GROUP_ID: str = "profile_projection"

chat_config = ChatConfig()
