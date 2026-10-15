import asyncio
import contextlib
import logging
import os
from asyncio.subprocess import DEVNULL, PIPE
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from app.core.services.media.dtos import HlsJob, HlsRendition
from app.core.services.media.exceptions import (
    MediaTranscodeFailedError,
    MediaTranscodeTimeoutError,
    MediaTranscodeUnavailableError,
)
from app.core.services.media.service import MediaTranscoder

logger = logging.getLogger(__name__)

HDR_TO_SDR_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)

MUXERS: dict[str, str] = {
    "mp4": "mp4",
    "mov": "mov",
    "webm": "webm",
    "avi": "avi",
}

ROTATION_FILTERS: dict[int, str] = {
    90: "transpose=cclock",
    180: "hflip,vflip",
    270: "transpose=clock",
}

STDERR_TAIL_BYTES = 1024
PROBE_OUTPUT_MAX_BYTES = 1024 * 1024
MAX_GRID_TILES = 1024


@dataclass
class FfmpegMediaTranscoder(MediaTranscoder):
    binary: str = field(default="ffmpeg")
    probe_binary: str = field(default="ffprobe")
    frame_timeout_seconds: float = field(default=30.0)
    remux_timeout_seconds: float = field(default=120.0)
    transcode_timeout_seconds: float = field(default=900.0)
    threads: int = field(default=2)
    nice: int = field(default=10)
    concurrency: int = field(default=1)

    def __post_init__(self) -> None:
        self._transcode_slots = asyncio.Semaphore(max(1, self.concurrency))

    async def decode_image(self, source: Path, destination: Path, *, max_pixels: int) -> None:
        layout = await self._probe_layout(source)
        width, height = layout["width"], layout["height"]
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise MediaTranscodeFailedError(f"image size {width}x{height} is out of bounds")

        args = [*self._base_args(), "-i", str(source)]
        graph = layout.get("graph")
        if graph is not None:
            args += ["-filter_complex", graph, "-map", "[img]"]
        else:
            args += ["-map", "0:v:0"]
        args += ["-frames:v", "1", "-f", "image2", "-c:v", "png", str(destination)]

        await self._run(args, timeout=self.frame_timeout_seconds)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise MediaTranscodeFailedError("image could not be decoded")

    async def _probe_layout(self, source: Path) -> dict[str, Any]:
        args = [
            "-v", "error", "-hide_banner",
            "-print_format", "json",
            "-show_streams", "-show_stream_groups",
            "-i", str(source),
        ]
        raw = await self._run(args, timeout=self.frame_timeout_seconds, binary=self.probe_binary)
        try:
            payload = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise MediaTranscodeFailedError("probe output is not valid json") from exc
        if not isinstance(payload, dict):
            raise MediaTranscodeFailedError("unexpected probe output")

        for group in payload.get("stream_groups") or []:
            if isinstance(group, dict) and group.get("type") == "Tile Grid":
                return self._grid_layout(group)

        streams = [
            stream for stream in payload.get("streams") or []
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ]
        if not streams:
            raise MediaTranscodeFailedError("no image stream")
        try:
            return {"width": int(streams[0].get("width") or 0), "height": int(streams[0].get("height") or 0)}
        except (TypeError, ValueError) as exc:
            raise MediaTranscodeFailedError("image dimensions are unreadable") from exc

    @staticmethod
    def _grid_layout(group: dict[str, Any]) -> dict[str, Any]:
        components = group.get("components") or []
        grid = components[0] if components and isinstance(components[0], dict) else {}
        tiles = [tile for tile in grid.get("subcomponents") or [] if isinstance(tile, dict)]
        if not tiles or len(tiles) > MAX_GRID_TILES:
            raise MediaTranscodeFailedError("unsupported tile grid")

        try:
            width, height = int(grid["width"]), int(grid["height"])
            crop_x, crop_y = int(grid.get("horizontal_offset", 0)), int(grid.get("vertical_offset", 0))
            inputs = "".join(f"[0:{int(tile['stream_index'])}]" for tile in tiles)
            layout = "|".join(
                f"{int(tile['tile_horizontal_offset'])}_{int(tile['tile_vertical_offset'])}"
                for tile in tiles
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaTranscodeFailedError("malformed tile grid") from exc

        graph = (
            f"{inputs}xstack=inputs={len(tiles)}:layout={layout}:fill=black,"
            f"crop={width}:{height}:{crop_x}:{crop_y}"
        )
        rotation = FfmpegMediaTranscoder._group_rotation(group)
        if rotation:
            graph += f",{ROTATION_FILTERS[rotation]}"
            if rotation != 180:
                width, height = height, width
        return {"width": width, "height": height, "graph": f"{graph}[img]"}

    @staticmethod
    def _group_rotation(group: dict[str, Any]) -> int:
        for item in group.get("side_data_list") or []:
            if not isinstance(item, dict) or "rotation" not in item:
                continue
            try:
                return round(float(item["rotation"]) / 90) * 90 % 360
            except (TypeError, ValueError):
                return 0
        return 0

    async def extract_frame(
        self, source: Path, destination: Path, *, offset_seconds: float, max_side: int, hdr: bool
    ) -> None:
        offsets = [offset_seconds, 0.0] if offset_seconds > 0 else [0.0]
        for offset in offsets:
            await self._run(
                self._frame_args(source, destination, offset=offset, max_side=max_side, hdr=hdr),
                timeout=self.frame_timeout_seconds,
            )
            if destination.is_file() and destination.stat().st_size > 0:
                return

        raise MediaTranscodeFailedError("no video frame could be decoded")

    async def strip_metadata(self, source: Path, destination: Path, *, container: str) -> None:
        muxer = MUXERS.get(container)
        if muxer is None:
            raise MediaTranscodeFailedError(f"unsupported container {container!r}")

        args = [
            *self._base_args(),
            "-i", str(source),
            "-map", "0:v", "-map", "0:a?",
            "-c", "copy",
            "-map_metadata", "-1",
            "-map_metadata:s", "-1",
            "-map_chapters", "-1",
        ]
        if muxer in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        args += ["-f", muxer, str(destination)]

        await self._run(args, timeout=self.remux_timeout_seconds)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise MediaTranscodeFailedError("remux produced no output")

    async def transcode_hls(self, source: Path, output_dir: Path, job: HlsJob) -> None:
        if not job.renditions:
            raise MediaTranscodeFailedError("no renditions requested")

        async with self._transcode_slots:
            await self._run(
                self.hls_args(source, output_dir, job),
                timeout=self.transcode_timeout_seconds,
            )

        for rendition in job.renditions:
            for suffix in (".m3u8", ".mp4"):
                produced = output_dir / f"{rendition.name}{suffix}"
                if not produced.is_file() or produced.stat().st_size == 0:
                    raise MediaTranscodeFailedError(f"missing output {produced.name}")

    def hls_args(self, source: Path, output_dir: Path, job: HlsJob) -> list[str]:
        prefix = f"{HDR_TO_SDR_FILTER}," if job.hdr else ""
        count = len(job.renditions)
        splits = "".join(f"[s{i}]" for i in range(count))
        scales = ";".join(
            f"[s{i}]scale={r.width}:{r.height}:flags=bicubic,setsar=1[v{i}]"
            for i, r in enumerate(job.renditions)
        )
        graph = f"[0:v:0]{prefix}split={count}{splits};{scales}"

        args = [
            *self._base_args(),
            "-threads", str(self.threads),
            "-i", str(source),
            "-filter_complex", graph,
            "-filter_complex_threads", str(self.threads),
        ]
        for index, rendition in enumerate(job.renditions):
            args += self._rendition_args(index, rendition, output_dir, job)
        return args

    def _rendition_args(
        self, index: int, rendition: HlsRendition, output_dir: Path, job: HlsJob
    ) -> list[str]:
        args = ["-map", f"[v{index}]"]
        if job.has_audio:
            args += ["-map", "0:a:0"]

        args += [
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-c:v", "libx264",
            "-preset", job.preset,
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-crf", str(job.crf),
            "-maxrate", f"{rendition.video_kbps}k",
            "-bufsize", f"{rendition.video_kbps * 2}k",
            "-force_key_frames", f"expr:gte(t,n_forced*{job.segment_seconds})",
            "-fpsmax", str(job.max_fps),
            "-threads", str(self.threads),
        ]
        if job.has_audio:
            args += ["-c:a", "aac", "-b:a", f"{rendition.audio_kbps}k", "-ac", "2"]

        args += [
            "-f", "hls",
            "-hls_time", str(job.segment_seconds),
            "-hls_playlist_type", "vod",
            "-hls_segment_type", "fmp4",
            "-hls_flags", "single_file+independent_segments",
            "-hls_segment_filename", str(output_dir / f"{rendition.name}.mp4"),
            str(output_dir / f"{rendition.name}.m3u8"),
        ]
        return args

    def _frame_args(
        self, source: Path, destination: Path, *, offset: float, max_side: int, hdr: bool
    ) -> list[str]:
        scale = (
            f"scale=w='min(iw,{max_side})':h='min(ih,{max_side})'"
            ":force_original_aspect_ratio=decrease"
        )
        video_filter = f"{HDR_TO_SDR_FILTER},{scale}" if hdr else scale
        return [
            *self._base_args(),
            "-ss", f"{offset:.3f}",
            "-i", str(source),
            "-map", "0:v:0",
            "-frames:v", "1",
            "-an", "-sn", "-dn",
            "-vf", video_filter,
            "-f", "image2",
            "-c:v", "png",
            str(destination),
        ]

    @staticmethod
    def _base_args() -> list[str]:
        return ["-hide_banner", "-nostdin", "-v", "error", "-y"]

    async def _run(self, args: Sequence[str], *, timeout: float, binary: str | None = None) -> bytes:
        executable = binary or self.binary
        capture = binary is not None
        try:
            process = await asyncio.create_subprocess_exec(
                executable, *args, stdin=DEVNULL, stdout=PIPE if capture else DEVNULL, stderr=PIPE,
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
            raise MediaTranscodeUnavailableError(f"{executable} is not available") from exc
        except OSError as exc:
            raise MediaTranscodeUnavailableError(f"failed to spawn {executable}") from exc

        if self.nice > 0:
            with contextlib.suppress(OSError):
                os.setpriority(os.PRIO_PROCESS, process.pid, self.nice)

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError as exc:
            await self._terminate(process)
            raise MediaTranscodeTimeoutError(f"{executable} exceeded {timeout}s") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise

        if process.returncode != 0:
            logger.warning(
                "Media tool returned non-zero exit code",
                extra={
                    "binary": executable,
                    "exit_code": process.returncode,
                    "stderr": stderr[-STDERR_TAIL_BYTES:].decode("utf-8", "replace"),
                },
            )
            raise MediaTranscodeFailedError(f"{executable} exited with {process.returncode}")

        if capture and (not stdout or len(stdout) > PROBE_OUTPUT_MAX_BYTES):
            raise MediaTranscodeFailedError("probe output is empty or too large")
        return stdout or b""

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            logger.error("ffmpeg process did not exit after kill")
