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

    MAX_PINNED_CHATS: int = 5

    MAX_PINNED_MESSAGES: int = 100
    PINNED_MESSAGES_PAGE_SIZE: int = 20
    PINNED_MESSAGES_MAX_PAGE_SIZE: int = 100
    PIN_RATE_LIMIT_TIMES: int = 20
    PIN_RATE_LIMIT_SECONDS: int = 60

    MAX_FORWARD_MESSAGES: int = 100
    FORWARD_MANY_RATE_LIMIT_TIMES: int = 30
    FORWARD_MANY_RATE_LIMIT_SECONDS: int = 60

    READ_MARKS_MAX_MEMBERS: int = 100
    READ_MARKS_RETENTION_DAYS: int = 7
    READ_MARKS_CLEANUP_BATCH_SIZE: int = 5_000
    READ_MARKS_CLEANUP_MAX_BATCHES: int = 50
    READ_MARKS_CLEANUP_INTERVAL_MINUTES: int = 10

    TYPING_TTL_SECONDS: int = 6
    TYPING_BROADCAST_INTERVAL_MS: int = 3_000
    TYPING_CONTEXT_TTL_SECONDS: int = 15
    TYPING_MAX_TRACKED_CHATS: int = 64

    CHAT_MEMBERS_PREVIEW_LIMIT: int = 3

    MESSAGE_SEARCH_MIN_QUERY_LENGTH: int = 2
    MESSAGE_SEARCH_MAX_QUERY_LENGTH: int = 150
    MESSAGE_SEARCH_LIMIT: int = 30
    MESSAGE_SEARCH_MAX_LIMIT: int = 50

    MESSAGE_SEARCH_MAX_TERMS: int = 10
    MESSAGE_SEARCH_RATE_LIMIT_TIMES: int = 20
    MESSAGE_SEARCH_RATE_LIMIT_SECONDS: int = 60

    CHAT_USERNAME_MIN_LENGTH: int = 5
    CHAT_USERNAME_MAX_LENGTH: int = 32
    CHAT_USERNAME_RESERVED: frozenset[str] = frozenset({
        "admin", "administrator", "moderator", "support", "help", "system",
        "official", "security", "settings", "search", "invites", "messages",
        "members", "reactions", "username", "chatix", "telegram", "root",
    })
    CHAT_USERNAME_RATE_LIMIT_TIMES: int = 10
    CHAT_USERNAME_RATE_LIMIT_SECONDS: int = 300

    PUBLIC_CHAT_SEARCH_MIN_QUERY_LENGTH: int = 2
    PUBLIC_CHAT_SEARCH_MAX_QUERY_LENGTH: int = 64
    PUBLIC_CHAT_SEARCH_LIMIT: int = 20
    PUBLIC_CHAT_SEARCH_MAX_LIMIT: int = 50
    PUBLIC_CHAT_SEARCH_MAX_TERMS: int = 5
    PUBLIC_CHAT_SEARCH_RATE_LIMIT_TIMES: int = 20
    PUBLIC_CHAT_SEARCH_RATE_LIMIT_SECONDS: int = 60

    INVITE_LINK_CODE_BYTES: int = 12
    INVITE_LINK_NAME_MAX_LENGTH: int = 32
    INVITE_LINK_MAX_USAGE_LIMIT: int = 99_999
    MAX_INVITE_LINKS_PER_CHAT: int = 100
    INVITE_LINKS_PAGE_SIZE: int = 50
    INVITE_LINKS_MAX_PAGE_SIZE: int = 100
    INVITE_LINK_CREATE_RATE_LIMIT_TIMES: int = 20
    INVITE_LINK_CREATE_RATE_LIMIT_SECONDS: int = 300
    INVITE_PREVIEW_RATE_LIMIT_TIMES: int = 30
    INVITE_PREVIEW_RATE_LIMIT_SECONDS: int = 60
    INVITE_JOIN_RATE_LIMIT_TIMES: int = 10
    INVITE_JOIN_RATE_LIMIT_SECONDS: int = 300

    MAX_SLOW_MODE_SECONDS: int = 86_400
    CHAT_STAFF_MIN_ROLE_LEVEL: int = 80
    CHAT_EDITOR_MIN_ROLE_LEVEL: int = 80

    WS_ACTIVE_SUBSCRIBER_SCAN_COUNT: int = 1_000
    WS_REPLAY_BATCH_SIZE: int = 50
    WS_MAX_CLIENT_FRAME_BYTES: int = 65_536
    RATE_LIMIT_MESSAGES_PER_SECOND: int = 10
    RATE_LIMIT_READ_RECEIPTS_PER_SECOND: int = 5

    READ_RECEIPTS_COALESCE_WINDOW_MS: int = 500
    READ_RECEIPTS_COALESCE_TICK_MS: int = 100
    READ_RECEIPTS_COALESCE_MAX_KEYS_PER_TICK: int = 1_000

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

    ATTACHMENT_IMAGE_MAX_PIXELS: int = 100_000_000
    ATTACHMENT_PREVIEW_SIZES: tuple[int, ...] = (320, 800, 1280)
    ATTACHMENT_PREVIEW_FORMAT: str = "webp"
    ATTACHMENT_PREVIEW_QUALITY: int = 80
    ATTACHMENT_ORIGINAL_QUALITY: int = 92
    ATTACHMENT_POSTER_OFFSET_SECONDS: float = 0.0
    ATTACHMENT_POSTER_MAX_SIDE: int = 1_920

    VIDEO_FRAME_TIMEOUT_SECONDS: float = 30.0
    VIDEO_REMUX_TIMEOUT_SECONDS: float = 120.0
    VIDEO_HLS_RENDITIONS: dict[int, int] = {360: 800, 720: 2_500, 1080: 5_000}
    VIDEO_HLS_AUDIO_KBPS: int = 128
    VIDEO_HLS_SEGMENT_SECONDS: int = 4
    VIDEO_HLS_CRF: int = 23
    VIDEO_HLS_PRESET: str = "veryfast"
    VIDEO_HLS_MAX_FPS: int = 60
    VIDEO_TRANSCODE_TIMEOUT_SECONDS: int = 900
    VIDEO_TRANSCODE_THREADS: int = 2
    VIDEO_TRANSCODE_CONCURRENCY: int = 1
    VIDEO_TRANSCODE_NICE: int = 10
    VIDEO_TRANSCODE_MAX_SOURCE_SIDE: int = 4_096
    VIDEO_TRANSCODE_MAX_DURATION_SECONDS: int = 3 * 3_600
    VIDEO_TRANSCODE_MAX_ATTEMPTS: int = 3
    VIDEO_TRANSCODE_STALE_AFTER_SECONDS: int = 1_800
    VIDEO_TRANSCODE_SWEEP_INTERVAL_MINUTES: int = 10
    VIDEO_TRANSCODE_SWEEP_BATCH_SIZE: int = 100

    HLS_URL_TTL: int = 7_200
    HLS_URL_TTL_BUCKET: int = 3_600
    HLS_SEGMENT_URL_TTL: int = 10_800
    HLS_PLAYLIST_CACHE_TTL: int = 3_600
    HLS_PLAYLIST_MAX_BYTES: int = 1024 * 1024
    HLS_PUBLIC_BASE_URL: str = ""

    SHARED_MEDIA_PAGE_SIZE: int = 30
    SHARED_MEDIA_MAX_PAGE_SIZE: int = 100

    ATTACHMENT_BUCKET: str = "chat-attachments"
    ATTACHMENT_BUCKET_PENDING: str = "chat-pending-attachments"
    AVATAR_BUCKET: str = "profiles"

    CHAT_AVATAR_BUCKET: str = "chat-avatars"
    CHAT_AVATAR_BUCKET_PENDING: str = "chat-pending-avatars"
    CHAT_AVATAR_MAX_SIZE: int = 5 * 1024 * 1024
    CHAT_AVATAR_MAX_PIXELS: int = 10_000_000
    CHAT_AVATAR_ALLOWED_MIMES: frozenset[str] = frozenset({
        "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    })
    CHAT_AVATAR_SIZES: tuple[int, ...] = (32, 64, 256, 512)
    CHAT_AVATAR_FORMATS: tuple[str, ...] = ("jpg", "webp", "avif")
    CHAT_AVATAR_UPLOAD_TTL: int = 600
    CHAT_AVATAR_RATE_LIMIT_TIMES: int = 10
    CHAT_AVATAR_RATE_LIMIT_SECONDS: int = 300

    RATE_LIMIT_REACTIONS_PER_SECOND: int = 10
    MAX_REACTION_LENGTH: int = 32

    REACTIONS_CATALOG_CACHE_TTL: int = 300

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

    PROFILE_PROJECTION_EVENTS: frozenset[str] = frozenset({
        "profiles.profile.created",
        "profiles.profile.updated",
    })

    BLOCK_PROJECTION_GROUP_ID: str = "chat_block_projection"
    USER_BLOCKED_EVENT: str = "profiles.user.blocked"
    USER_UNBLOCKED_EVENT: str = "profiles.user.unblocked"

chat_config = ChatConfig()
