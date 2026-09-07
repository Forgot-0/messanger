from dataclasses import dataclass
from enum import StrEnum


class MediaProbeFailureReason(StrEnum):
    METADATA_UNREADABLE = "metadata_unreadable"
    PROBE_TIMEOUT = "probe_timeout"
    INVALID_MEDIA = "invalid_media"
    PROBE_UNAVAILABLE = "probe_unavailable"


@dataclass(frozen=True)
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    frame_rate: float | None = None
    is_attached_pic: bool = False


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    streams: tuple[StreamInfo, ...]
    format_name: str | None = None

    @property
    def video_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(
            stream
            for stream in self.streams
            if stream.codec_type == "video" and not stream.is_attached_pic
        )

    @property
    def audio_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.codec_type == "audio")
