from app.core.services.media.dtos import MediaProbeFailureReason


class MediaProbeError(Exception):
    permanent: bool = True
    reason: MediaProbeFailureReason = MediaProbeFailureReason.INVALID_MEDIA

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.reason.value)


class InvalidMediaError(MediaProbeError):
    permanent = True
    reason = MediaProbeFailureReason.INVALID_MEDIA


class MediaMetadataUnreadableError(MediaProbeError):
    permanent = True
    reason = MediaProbeFailureReason.METADATA_UNREADABLE


class MediaProbeTimeoutError(MediaProbeError):
    permanent = True
    reason = MediaProbeFailureReason.PROBE_TIMEOUT


class MediaProbeUnavailableError(MediaProbeError):
    permanent = False
    reason = MediaProbeFailureReason.PROBE_UNAVAILABLE
