import sys
from pathlib import Path
from typing import Any

import pytest

from app.core.services.media.dtos import StreamInfo
from app.core.services.media.exceptions import (
    MediaTranscodeFailedError,
    MediaTranscodeTimeoutError,
    MediaTranscodeUnavailableError,
)
from app.core.services.media.probe.ffprobe import parse_ffprobe_output
from app.core.services.media.transcode.ffmpeg import HDR_TO_SDR_FILTER, FfmpegMediaTranscoder


def probe_payload(**video: Any) -> dict[str, Any]:
    return {
        "format": {"duration": "4.5", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [{"index": 0, "codec_type": "video", "width": 1920, "height": 1080, **video}],
    }


@pytest.mark.unit
class TestProbeParsing:

    def test_display_matrix_rotation_is_read(self) -> None:
        info = parse_ffprobe_output(
            probe_payload(side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}])
        )

        stream = info.video_streams[0]
        assert stream.rotation == 270
        assert stream.display_size == (1080, 1920)

    def test_legacy_rotate_tag_is_read(self) -> None:
        info = parse_ffprobe_output(probe_payload(tags={"rotate": "180"}))

        assert info.video_streams[0].rotation == 180
        assert info.video_streams[0].display_size == (1920, 1080)

    @pytest.mark.parametrize("raw", [None, "garbage", True, float("nan")])
    def test_unreadable_rotation_means_no_rotation(self, raw: Any) -> None:
        info = parse_ffprobe_output(probe_payload(side_data_list=[{"rotation": raw}]))

        assert info.video_streams[0].rotation == 0

    @pytest.mark.parametrize(
        "transfer,hdr", [("arib-std-b67", True), ("SMPTE2084", True), ("bt709", False), (None, False)]
    )
    def test_hdr_is_detected_from_the_transfer(self, transfer: str | None, hdr: bool) -> None:
        info = parse_ffprobe_output(probe_payload(color_transfer=transfer))

        assert info.video_streams[0].is_hdr is hdr

    def test_display_size_is_unknown_without_dimensions(self) -> None:
        assert StreamInfo(index=0, codec_type="video").display_size is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestFfmpegProcess:

    async def test_missing_binary_is_transient(self, tmp_path: Path) -> None:
        transcoder = FfmpegMediaTranscoder(binary=str(tmp_path / "no-ffmpeg"))

        with pytest.raises(MediaTranscodeUnavailableError) as exc_info:
            await transcoder.strip_metadata(tmp_path / "a", tmp_path / "b.mp4", container="mp4")

        assert exc_info.value.permanent is False

    async def test_non_zero_exit_is_permanent(self, tmp_path: Path) -> None:
        transcoder = FfmpegMediaTranscoder(binary="false")

        with pytest.raises(MediaTranscodeFailedError):
            await transcoder.strip_metadata(tmp_path / "a", tmp_path / "b.mp4", container="mp4")

    async def test_runaway_process_is_killed_on_timeout(self, tmp_path: Path) -> None:
        script = tmp_path / "slow"
        script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
        script.chmod(0o755)
        transcoder = FfmpegMediaTranscoder(binary=str(script), remux_timeout_seconds=0.2)

        with pytest.raises(MediaTranscodeTimeoutError):
            await transcoder.strip_metadata(tmp_path / "a", tmp_path / "b.mp4", container="mp4")

    async def test_unknown_container_is_refused_without_spawning(self, tmp_path: Path) -> None:
        transcoder = FfmpegMediaTranscoder(binary=str(tmp_path / "no-ffmpeg"))

        with pytest.raises(MediaTranscodeFailedError):
            await transcoder.strip_metadata(tmp_path / "a", tmp_path / "b.mkv", container="mkv")

    async def test_hdr_frame_is_tone_mapped_before_scaling(self, tmp_path: Path) -> None:
        args = FfmpegMediaTranscoder()._frame_args(
            tmp_path / "a", tmp_path / "b.png", offset=0.0, max_side=1280, hdr=True
        )

        assert args[args.index("-vf") + 1].startswith(f"{HDR_TO_SDR_FILTER},scale=")

    async def test_successful_run_without_output_is_a_failure(self, tmp_path: Path) -> None:
        transcoder = FfmpegMediaTranscoder(binary="true")

        with pytest.raises(MediaTranscodeFailedError):
            await transcoder.extract_frame(
                tmp_path / "a", tmp_path / "frame.png", offset_seconds=1.0, max_side=1280, hdr=False
            )
