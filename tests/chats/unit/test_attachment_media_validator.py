import math
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest

from app.chats.config import chat_config
from app.chats.exceptions import AttachmentMediaValidationError, AttachmentRejectionReason
from app.chats.models.attachment import AttachmentType, MessageAttachment
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.core.services.media.dtos import MediaInfo, StreamInfo
from app.core.services.media.exceptions import (
    InvalidMediaError,
    MediaMetadataUnreadableError,
    MediaProbeTimeoutError,
    MediaProbeUnavailableError,
)
from app.core.services.media.service import MediaProbeService
from app.core.services.storage.dtos import ObjectStat
from app.core.services.storage.exceptions import ObjectTooLargeError
from tests.mocks import FakeStorageService


@dataclass
class FakeMediaProbe(MediaProbeService):
    media_info: MediaInfo | None = None
    error: Exception | None = None
    probed_paths: list[Path] = field(default_factory=list)

    async def probe(self, path: Path) -> MediaInfo:
        self.probed_paths.append(path)
        if self.error is not None:
            raise self.error
        assert self.media_info is not None
        return self.media_info


@dataclass
class RecordingStorage(FakeStorageService):
    download_error: Exception | None = None

    async def download_to_path(
        self, bucket_name: str, file_key: str, destination: Path, *,
        max_bytes: int, stat: ObjectStat | None = None,
    ) -> int:
        if self.download_error is not None:
            raise self.download_error
        destination.write_bytes(b"media-bytes")
        return len(b"media-bytes")


def make_attachment(attachment_type: AttachmentType) -> MessageAttachment:
    return MessageAttachment.create(
        chat_id=uuid4(),
        uploader_id=1,
        attachment_type=attachment_type,
        s3_key="chats/x/y/media",
        mime_type="audio/ogg",
        original_filename="media",
        size=1024,
    )


def audio_info(duration: float = 5.0) -> MediaInfo:
    return MediaInfo(
        duration=duration,
        streams=(StreamInfo(index=0, codec_type="audio", codec_name="opus"),),
    )


def video_info(
    duration: float = 5.0,
    width: int | None = 480,
    height: int | None = 480,
    frame_rate: float | None = 30.0,
    streams: tuple[StreamInfo, ...] | None = None,
) -> MediaInfo:
    return MediaInfo(
        duration=duration,
        streams=streams
        or (
            StreamInfo(
                index=0, codec_type="video", codec_name="h264",
                width=width, height=height, frame_rate=frame_rate,
            ),
        ),
    )


def stat(size: int = 1024) -> ObjectStat:
    return ObjectStat(bucket_name="pending", file_key="chats/x/y/media", size=size)


@pytest.fixture
def probe() -> FakeMediaProbe:
    return FakeMediaProbe()


@pytest.fixture
def storage() -> RecordingStorage:
    return RecordingStorage()


@pytest.fixture
def validator(storage: RecordingStorage, probe: FakeMediaProbe) -> AttachmentMediaValidator:
    return AttachmentMediaValidator(storage_service=storage, media_probe_service=probe)


@pytest.mark.unit
@pytest.mark.chats
class TestRequiresProbe:

    @pytest.mark.parametrize(
        "attachment_type,expected",
        [
            (AttachmentType.VOICE, True),
            (AttachmentType.VIDEO_NOTE, True),
            (AttachmentType.IMAGE, False),
            (AttachmentType.VIDEO, False),
            (AttachmentType.FILE, False),
        ],
    )
    def test_only_voice_and_video_note_are_probed(
        self, attachment_type: AttachmentType, expected: bool
    ) -> None:
        assert AttachmentMediaValidator.requires_probe(attachment_type) is expected


@pytest.mark.unit
@pytest.mark.chats
@pytest.mark.asyncio
class TestVoiceValidation:

    async def test_valid_voice_gets_its_duration_applied(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = audio_info(duration=12.4)
        attachment = make_attachment(AttachmentType.VOICE)

        await validator.validate_and_apply(attachment, stat())

        assert attachment.duration_seconds == 12

    async def test_duration_is_rounded_up_from_zero_to_one_second(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = audio_info(duration=0.4)
        attachment = make_attachment(AttachmentType.VOICE)

        await validator.validate_and_apply(attachment, stat())

        assert attachment.duration_seconds == 1

    async def test_duration_over_the_limit_is_rejected(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = audio_info(
            duration=chat_config.MAX_VOICE_DURATION_SECONDS + 1
        )

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert exc_info.value.reason is AttachmentRejectionReason.DURATION_LIMIT_EXCEEDED
        assert exc_info.value.limit == chat_config.MAX_VOICE_DURATION_SECONDS

    async def test_voice_carrying_a_video_stream_is_rejected(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = MediaInfo(
            duration=5.0,
            streams=(
                StreamInfo(index=0, codec_type="audio"),
                StreamInfo(index=1, codec_type="video", width=100, height=100),
            ),
        )

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert exc_info.value.reason is AttachmentRejectionReason.INVALID_MEDIA

    async def test_voice_without_an_audio_stream_is_rejected(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = MediaInfo(duration=5.0, streams=())

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert exc_info.value.reason is AttachmentRejectionReason.INVALID_MEDIA

    @pytest.mark.parametrize("duration", [0.0, -1.0, math.inf, math.nan])
    async def test_unusable_duration_is_metadata_unreadable(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe, duration: float
    ) -> None:
        probe.media_info = audio_info(duration=duration)

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert exc_info.value.reason is AttachmentRejectionReason.METADATA_UNREADABLE


@pytest.mark.unit
@pytest.mark.chats
@pytest.mark.asyncio
class TestVideoNoteValidation:

    async def test_valid_note_gets_duration_and_resolution(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = video_info(duration=8.0, width=480, height=480)
        attachment = make_attachment(AttachmentType.VIDEO_NOTE)

        await validator.validate_and_apply(attachment, stat())

        assert attachment.duration_seconds == 8
        assert (attachment.width, attachment.height) == (480, 480)

    async def test_resolution_over_the_limit_is_rejected(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        oversize = chat_config.MAX_VIDEO_NOTE_RESOLUTION_PX + 1
        probe.media_info = video_info(width=oversize, height=100)

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(
                make_attachment(AttachmentType.VIDEO_NOTE), stat()
            )

        assert exc_info.value.reason is AttachmentRejectionReason.RESOLUTION_LIMIT_EXCEEDED
        assert exc_info.value.limit == chat_config.MAX_VIDEO_NOTE_RESOLUTION_PX

    async def test_the_limit_itself_is_allowed(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        edge = chat_config.MAX_VIDEO_NOTE_RESOLUTION_PX
        probe.media_info = video_info(width=edge, height=edge)
        attachment = make_attachment(AttachmentType.VIDEO_NOTE)

        await validator.validate_and_apply(attachment, stat())

        assert (attachment.width, attachment.height) == (edge, edge)

    async def test_frame_rate_over_the_limit_is_rejected(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = video_info(frame_rate=chat_config.MAX_VIDEO_NOTE_FPS + 1)

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(
                make_attachment(AttachmentType.VIDEO_NOTE), stat()
            )

        assert exc_info.value.reason is AttachmentRejectionReason.FRAME_RATE_LIMIT_EXCEEDED

    async def test_unknown_frame_rate_is_not_a_rejection(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = video_info(frame_rate=None)
        attachment = make_attachment(AttachmentType.VIDEO_NOTE)

        await validator.validate_and_apply(attachment, stat())

        assert attachment.duration_seconds == 5

    @pytest.mark.parametrize("width,height", [(None, 480), (480, None), (0, 480), (480, 0)])
    async def test_missing_dimensions_are_metadata_unreadable(
        self,
        validator: AttachmentMediaValidator,
        probe: FakeMediaProbe,
        width: int | None,
        height: int | None,
    ) -> None:
        probe.media_info = video_info(width=width, height=height)

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(
                make_attachment(AttachmentType.VIDEO_NOTE), stat()
            )

        assert exc_info.value.reason is AttachmentRejectionReason.METADATA_UNREADABLE

    @pytest.mark.parametrize("stream_count", [0, 2])
    async def test_note_must_carry_exactly_one_video_stream(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe, stream_count: int
    ) -> None:
        probe.media_info = MediaInfo(
            duration=5.0,
            streams=tuple(
                StreamInfo(index=i, codec_type="video", width=100, height=100)
                for i in range(stream_count)
            ),
        )

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(
                make_attachment(AttachmentType.VIDEO_NOTE), stat()
            )

        assert exc_info.value.reason is AttachmentRejectionReason.INVALID_MEDIA

    async def test_cover_art_does_not_count_as_a_video_stream(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = MediaInfo(
            duration=5.0,
            streams=(
                StreamInfo(index=0, codec_type="video", width=100, height=100),
                StreamInfo(
                    index=1, codec_type="video", width=50, height=50, is_attached_pic=True
                ),
            ),
        )
        attachment = make_attachment(AttachmentType.VIDEO_NOTE)

        await validator.validate_and_apply(attachment, stat())

        assert (attachment.width, attachment.height) == (100, 100)


@pytest.mark.unit
@pytest.mark.chats
@pytest.mark.asyncio
class TestSizeAndProbeFailures:

    @pytest.mark.parametrize("size", [0, -1])
    async def test_empty_object_is_invalid_media(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe, size: int
    ) -> None:
        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(
                make_attachment(AttachmentType.VOICE), stat(size=size)
            )

        assert exc_info.value.reason is AttachmentRejectionReason.INVALID_MEDIA
        assert probe.probed_paths == []

    async def test_object_over_the_size_limit_is_rejected_before_probing(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(
                make_attachment(AttachmentType.VOICE),
                stat(size=chat_config.MAX_VOICE_SIZE + 1),
            )

        assert exc_info.value.reason is AttachmentRejectionReason.SIZE_LIMIT_EXCEEDED
        assert probe.probed_paths == []

    async def test_storage_refusing_an_oversized_object_maps_to_size_limit(
        self,
        storage: RecordingStorage,
        validator: AttachmentMediaValidator,
    ) -> None:
        storage.download_error = ObjectTooLargeError(
            bucket_name="pending", file_key="k", max_bytes=1
        )

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert exc_info.value.reason is AttachmentRejectionReason.SIZE_LIMIT_EXCEEDED

    @pytest.mark.parametrize(
        "error,reason",
        [
            (MediaProbeTimeoutError(), AttachmentRejectionReason.PROBE_TIMEOUT),
            (MediaMetadataUnreadableError(), AttachmentRejectionReason.METADATA_UNREADABLE),
            (InvalidMediaError(), AttachmentRejectionReason.INVALID_MEDIA),
        ],
    )
    async def test_permanent_probe_errors_become_rejections(
        self,
        validator: AttachmentMediaValidator,
        probe: FakeMediaProbe,
        error: Exception,
        reason: AttachmentRejectionReason,
    ) -> None:
        probe.error = error

        with pytest.raises(AttachmentMediaValidationError) as exc_info:
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert exc_info.value.reason is reason

    async def test_transient_probe_failure_is_not_swallowed(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.error = MediaProbeUnavailableError()

        with pytest.raises(MediaProbeUnavailableError):
            await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

    async def test_temporary_file_is_cleaned_up_after_probing(
        self, validator: AttachmentMediaValidator, probe: FakeMediaProbe
    ) -> None:
        probe.media_info = audio_info()

        await validator.validate_and_apply(make_attachment(AttachmentType.VOICE), stat())

        assert len(probe.probed_paths) == 1
        assert not probe.probed_paths[0].exists()
