import os
import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pyvips  # type: ignore[import-untyped]

from app.core.services.media.dtos import HlsJob, MediaInfo, StreamInfo
from app.core.services.media.service import MediaProbeService, MediaTranscoder

GPS_LATITUDE = struct.pack("<6I", 55, 1, 45, 1, 2112, 100)


def solid_image(width: int, height: int, *, bands: int = 3, color: tuple[int, ...] = (200, 30, 30)) -> pyvips.Image:
    image = pyvips.Image.black(width, height, bands=bands) + list(color[:bands])
    # Градиент по x — чтобы превью и thumbhash были не из одного пикселя.
    image = image + pyvips.Image.xyz(width, height)[0] / max(1, width) * 40
    return image.cast("uchar")


def make_jpeg(
    width: int = 640,
    height: int = 480,
    *,
    orientation: int | None = None,
    gps: bool = False,
) -> bytes:
    data = solid_image(width, height).write_to_buffer(".jpg", Q=90, keep=pyvips.enums.ForeignKeep.NONE)
    if orientation is None and not gps:
        return data
    segment = _exif_app1(orientation, gps)
    return data[:2] + segment + data[2:]


def make_png(width: int = 320, height: int = 240, *, alpha: bool = True) -> bytes:
    bands = 4 if alpha else 3
    return solid_image(width, height, bands=bands, color=(10, 120, 220, 128)).write_to_buffer(".png")


def make_gif(width: int = 120, height: int = 80) -> bytes:
    return solid_image(width, height).write_to_buffer(".gif")


def _exif_app1(orientation: int | None, gps: bool) -> bytes:
    """Минимальный TIFF/EXIF: IFD0 с Orientation и указателем на GPS IFD (широта 55°45'21.12")."""
    ifd0: list[tuple[int, int, int, bytes | None]] = []
    if orientation is not None:
        ifd0.append((0x0112, 3, 1, struct.pack("<HH", orientation, 0)))
    if gps:
        ifd0.append((0x8825, 4, 1, None))

    ifd0_offset = 8
    ifd0_size = 2 + 12 * len(ifd0) + 4
    gps_offset = ifd0_offset + ifd0_size
    gps_size = 2 + 12 * 2 + 4
    data_offset = gps_offset + gps_size

    tiff = bytearray(b"II*\x00" + struct.pack("<I", ifd0_offset))
    tiff += struct.pack("<H", len(ifd0))
    for tag, kind, count, value in ifd0:
        tiff += struct.pack("<HHI", tag, kind, count)
        tiff += value if value is not None else struct.pack("<I", gps_offset)
    tiff += struct.pack("<I", 0)

    if gps:
        tiff += struct.pack("<H", 2)
        tiff += struct.pack("<HHI", 0x0001, 2, 2) + b"N\x00\x00\x00"
        tiff += struct.pack("<HHII", 0x0002, 5, 3, data_offset)
        tiff += struct.pack("<I", 0)
        tiff += GPS_LATITUDE

    payload = b"Exif\x00\x00" + bytes(tiff)
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def video_info(
    *,
    width: int = 1280,
    height: int = 720,
    duration: float = 12.4,
    rotation: int = 0,
    audio: bool = True,
    color_transfer: str | None = None,
) -> MediaInfo:
    streams = [
        StreamInfo(
            index=0, codec_type="video", codec_name="h264", width=width, height=height,
            frame_rate=30.0, rotation=rotation, color_transfer=color_transfer,
        )
    ]
    if audio:
        streams.append(StreamInfo(index=1, codec_type="audio", codec_name="aac"))
    return MediaInfo(duration=duration, streams=tuple(streams))


@dataclass
class FakeMediaProbe(MediaProbeService):
    media_info: MediaInfo | None = None
    error: Exception | None = None
    probed: list[Path] = field(default_factory=list)

    async def probe(self, path: Path) -> MediaInfo:
        self.probed.append(path)
        if self.error is not None:
            raise self.error
        assert self.media_info is not None
        return self.media_info


@dataclass
class FakeMediaTranscoder(MediaTranscoder):
    """Пишет то же, что пишет ffmpeg, но pyvips'ом и без видео: кадр — PNG нужного размера,
    ремукс — копия, HLS — пустые на вид, но непустые файлы рендиций."""

    frame_size: tuple[int, int] = (1280, 720)
    frame_error: Exception | None = None
    remux_error: Exception | None = None
    hls_error: Exception | None = None
    decode_error: Exception | None = None
    calls: list[str] = field(default_factory=list)
    hls_jobs: list[HlsJob] = field(default_factory=list)

    async def decode_image(self, source: Path, destination: Path, *, max_pixels: int) -> None:
        self.calls.append("decode_image")
        if self.decode_error is not None:
            raise self.decode_error
        solid_image(*self.frame_size).write_to_file(str(destination))

    async def extract_frame(
        self, source: Path, destination: Path, *, offset_seconds: float, max_side: int, hdr: bool
    ) -> None:
        self.calls.append(f"extract_frame:hdr={hdr}")
        if self.frame_error is not None:
            raise self.frame_error
        solid_image(*self.frame_size).write_to_file(str(destination))

    async def strip_metadata(self, source: Path, destination: Path, *, container: str) -> None:
        self.calls.append(f"strip_metadata:{container}")
        if self.remux_error is not None:
            raise self.remux_error
        destination.write_bytes(b"clean:" + source.read_bytes())

    async def transcode_hls(self, source: Path, output_dir: Path, job: HlsJob) -> None:
        self.calls.append("transcode_hls")
        self.hls_jobs.append(job)
        if self.hls_error is not None:
            raise self.hls_error
        for rendition in job.renditions:
            (output_dir / f"{rendition.name}.mp4").write_bytes(b"\x00" * 64)
            (output_dir / f"{rendition.name}.m3u8").write_text(
                "#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:4\n#EXT-X-PLAYLIST-TYPE:VOD\n"
                f'#EXT-X-MAP:URI="{rendition.name}.mp4",BYTERANGE="16@0"\n'
                f"#EXTINF:4.000000,\n#EXT-X-BYTERANGE:48@16\n{rendition.name}.mp4\n#EXT-X-ENDLIST\n"
            )


def media_tool(name: str) -> str | None:
    """Реальный ffmpeg/ffprobe для тестов, которые без него бессмысленны."""
    return os.environ.get(f"TEST_{name.upper()}_BINARY") or shutil.which(name)
