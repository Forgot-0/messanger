import sys
from pathlib import Path
from typing import Any

import pytest

from app.core.services.media.dtos import HlsJob, HlsRendition, StreamInfo
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


def job(*, hdr: bool = False, audio: bool = True) -> HlsJob:
    return HlsJob(
        renditions=(
            HlsRendition("v0", 640, 360, 800, 128),
            HlsRendition("v1", 1280, 720, 2500, 128),
        ),
        has_audio=audio,
        hdr=hdr,
        segment_seconds=4,
        crf=23,
        preset="veryfast",
        max_fps=60,
    )


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
class TestFfmpegArguments:

    def test_every_rendition_gets_its_own_scaled_output(self) -> None:
        args = FfmpegMediaTranscoder().hls_args(Path("/in.mov"), Path("/out"), job())

        graph = args[args.index("-filter_complex") + 1]
        assert graph.startswith("[0:v:0]split=2[s0][s1];")
        assert "[s0]scale=640:360" in graph and "[s1]scale=1280:720" in graph
        assert HDR_TO_SDR_FILTER not in graph
        assert args.count("-f") == 2 and args.count("hls") == 2
        assert "/out/v0.m3u8" in args and "/out/v1.m3u8" in args
        assert args[args.index("-hls_segment_filename") + 1] == "/out/v0.mp4"
        assert "single_file+independent_segments" in args
        assert args.count("-map_metadata") == 2

    def test_hdr_source_is_tone_mapped_once_before_the_split(self) -> None:
        args = FfmpegMediaTranscoder().hls_args(Path("/in.mov"), Path("/out"), job(hdr=True))

        graph = args[args.index("-filter_complex") + 1]
        assert graph.startswith(f"[0:v:0]{HDR_TO_SDR_FILTER},split=2")

    def test_silent_video_maps_no_audio(self) -> None:
        args = FfmpegMediaTranscoder().hls_args(Path("/in.mov"), Path("/out"), job(audio=False))

        assert "0:a:0" not in args
        assert "aac" not in args

    def test_tile_grid_is_stacked_and_cropped(self) -> None:
        layout = FfmpegMediaTranscoder._grid_layout({
            "type": "Tile Grid",
            "components": [{
                "width": 1000, "height": 700, "horizontal_offset": 0, "vertical_offset": 0,
                "subcomponents": [
                    {"stream_index": 0, "tile_horizontal_offset": 0, "tile_vertical_offset": 0},
                    {"stream_index": 1, "tile_horizontal_offset": 512, "tile_vertical_offset": 0},
                    {"stream_index": 2, "tile_horizontal_offset": 0, "tile_vertical_offset": 512},
                    {"stream_index": 3, "tile_horizontal_offset": 512, "tile_vertical_offset": 512},
                ],
            }],
        })

        assert (layout["width"], layout["height"]) == (1000, 700)
        assert layout["graph"] == (
            "[0:0][0:1][0:2][0:3]xstack=inputs=4:layout=0_0|512_0|0_512|512_512:fill=black,"
            "crop=1000:700:0:0[img]"
        )

    def test_rotated_tile_grid_swaps_the_dimensions(self) -> None:
        layout = FfmpegMediaTranscoder._grid_layout({
            "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}],
            "components": [{
                "width": 800, "height": 600,
                "subcomponents": [{"stream_index": 0, "tile_horizontal_offset": 0, "tile_vertical_offset": 0}],
            }],
        })

        assert (layout["width"], layout["height"]) == (600, 800)
        assert layout["graph"].endswith(",transpose=clock[img]")

    @pytest.mark.parametrize(
        "group",
        [
            {"components": [{"width": 10, "height": 10, "subcomponents": []}]},
            {"components": [{"height": 10, "subcomponents": [{"stream_index": 0}]}]},
        ],
    )
    def test_broken_tile_grid_is_a_permanent_failure(self, group: dict[str, Any]) -> None:
        with pytest.raises(MediaTranscodeFailedError):
            FfmpegMediaTranscoder._grid_layout(group)


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

    async def test_successful_run_without_output_is_a_failure(self, tmp_path: Path) -> None:
        transcoder = FfmpegMediaTranscoder(binary="true")

        with pytest.raises(MediaTranscodeFailedError):
            await transcoder.extract_frame(
                tmp_path / "a", tmp_path / "frame.png", offset_seconds=1.0, max_side=1280, hdr=False
            )
