import asyncio
from pathlib import Path

import pytest
import pyvips  # type: ignore[import-untyped]

from app.core.services.media.probe.ffprobe import FfprobeMediaProbeService
from app.core.services.media.transcode.ffmpeg import FfmpegMediaTranscoder
from tests.support.media import media_tool

FFMPEG = media_tool("ffmpeg")
FFPROBE = media_tool("ffprobe")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe are not installed"),
]


async def ffmpeg(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        FFMPEG, "-hide_banner", "-v", "error", "-y", *args,  # type: ignore[arg-type]
        stdin=asyncio.subprocess.DEVNULL,
    )
    assert await process.wait() == 0


async def make_clip(path: Path, *, rotation: int = 0, hdr: bool = False, location: bool = False) -> None:
    video_filter = (
        "format=yuv420p10le,setparams=color_trc=arib-std-b67:color_primaries=bt2020:colorspace=bt2020nc"
        if hdr else "format=yuv420p"
    )
    args = [
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "5", "-vf", video_filter, "-c:v", "libx264", "-c:a", "aac",
    ]
    if location:
        args += ["-metadata", "location=+55.7558+037.6173/", "-metadata", "title=secret"]
    plain = path.with_suffix(".plain.mov")
    await ffmpeg(*args, str(plain))
    if rotation:
        await ffmpeg("-display_rotation", str(rotation), "-i", str(plain), "-c", "copy", str(path))
    else:
        plain.rename(path)


@pytest.fixture
def transcoder() -> FfmpegMediaTranscoder:
    return FfmpegMediaTranscoder(binary=FFMPEG, nice=0)  # type: ignore[arg-type]


@pytest.fixture
def probe() -> FfprobeMediaProbeService:
    return FfprobeMediaProbeService(binary=FFPROBE)  # type: ignore[arg-type]


@pytest.mark.asyncio
class TestFfmpegTranscoder:

    async def test_poster_of_a_portrait_phone_video_is_upright(
        self, tmp_path: Path, transcoder: FfmpegMediaTranscoder, probe: FfprobeMediaProbeService
    ) -> None:
        source = tmp_path / "portrait.mov"
        await make_clip(source, rotation=90)
        info = await probe.probe(source)

        await transcoder.extract_frame(
            source, tmp_path / "poster.png", offset_seconds=0.0, max_side=1920, hdr=False
        )

        poster = pyvips.Image.new_from_file(str(tmp_path / "poster.png"))
        assert info.video_streams[0].display_size == (360, 640)
        assert (poster.width, poster.height) == (360, 640)

    async def test_hdr_poster_is_tone_mapped(
        self, tmp_path: Path, transcoder: FfmpegMediaTranscoder, probe: FfprobeMediaProbeService
    ) -> None:
        source = tmp_path / "hdr.mov"
        await make_clip(source, hdr=True)
        info = await probe.probe(source)

        await transcoder.extract_frame(
            source, tmp_path / "poster.png", offset_seconds=0.0, max_side=320, hdr=info.video_streams[0].is_hdr
        )

        poster = pyvips.Image.new_from_file(str(tmp_path / "poster.png"))
        assert info.video_streams[0].is_hdr
        assert (poster.width, poster.height) == (320, 180)

    async def test_remux_drops_the_location(
        self, tmp_path: Path, transcoder: FfmpegMediaTranscoder
    ) -> None:
        source = tmp_path / "located.mov"
        await make_clip(source, location=True)
        assert b"+55.7558+037.6173" in source.read_bytes()

        await transcoder.strip_metadata(source, tmp_path / "clean.mov", container="mov")

        cleaned = (tmp_path / "clean.mov").read_bytes()
        assert b"+55.7558+037.6173" not in cleaned
        assert b"secret" not in cleaned
