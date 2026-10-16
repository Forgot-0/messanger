import asyncio
import contextlib
import logging
import os
from asyncio.subprocess import DEVNULL, PIPE
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.core.services.media.exceptions import (
    MediaTranscodeFailedError,
    MediaTranscodeTimeoutError,
    MediaTranscodeUnavailableError,
)
from app.core.services.media.service import MediaTranscoder

logger = logging.getLogger(__name__)

# HLG/PQ → SDR BT.709. Без этого кадры HDR-видео с айфона выходят блёклыми.
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

STDERR_TAIL_BYTES = 1024


@dataclass
class FfmpegMediaTranscoder(MediaTranscoder):
    binary: str = field(default="ffmpeg")
    frame_timeout_seconds: float = field(default=30.0)
    remux_timeout_seconds: float = field(default=120.0)
    nice: int = field(default=10)

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

    async def _run(self, args: Sequence[str], *, timeout: float) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary, *args, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE,
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
            raise MediaTranscodeUnavailableError(f"{self.binary} is not available") from exc
        except OSError as exc:
            raise MediaTranscodeUnavailableError(f"failed to spawn {self.binary}") from exc

        if self.nice > 0:
            with contextlib.suppress(OSError):
                os.setpriority(os.PRIO_PROCESS, process.pid, self.nice)

        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError as exc:
            await self._terminate(process)
            raise MediaTranscodeTimeoutError(f"{self.binary} exceeded {timeout}s") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise

        if process.returncode != 0:
            logger.warning(
                "ffmpeg returned non-zero exit code",
                extra={
                    "exit_code": process.returncode,
                    "stderr": stderr[-STDERR_TAIL_BYTES:].decode("utf-8", "replace"),
                },
            )
            raise MediaTranscodeFailedError(f"{self.binary} exited with {process.returncode}")

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
