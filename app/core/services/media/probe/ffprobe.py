import asyncio
import logging
import math
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from app.core.services.media.dtos import MediaInfo, StreamInfo
from app.core.services.media.exceptions import (
    InvalidMediaError,
    MediaMetadataUnreadableError,
    MediaProbeTimeoutError,
    MediaProbeUnavailableError,
)
from app.core.services.media.service import MediaProbeService

logger = logging.getLogger(__name__)

_ABSENT_VALUES = frozenset({"", "n/a", "unknown", "none"})


@dataclass
class FfprobeMediaProbeService(MediaProbeService):
    binary: str = field(default="ffprobe")
    timeout_seconds: float = field(default=10.0)
    probe_size_bytes: int = field(default=5 * 1024 * 1024)
    analyze_duration_us: int = field(default=5_000_000)
    max_output_bytes: int = field(default=256 * 1024)
    max_streams: int = field(default=16)

    async def probe(self, path: Path) -> MediaInfo:
        if not path.is_file() or path.stat().st_size == 0:
            raise InvalidMediaError("empty or missing media file")

        raw_output = await self._run(path)

        try:
            payload = orjson.loads(raw_output)
        except orjson.JSONDecodeError as exc:
            raise MediaMetadataUnreadableError("probe output is not valid json") from exc

        if not isinstance(payload, dict):
            raise MediaMetadataUnreadableError("unexpected probe output structure")

        return parse_ffprobe_output(payload, max_streams=self.max_streams)

    async def _run(self, path: Path) -> bytes:
        args = [
            self.binary,
            "-v", "error",
            "-hide_banner",
            "-protocol_whitelist", "file",
            "-analyzeduration", str(self.analyze_duration_us),
            "-probesize", str(self.probe_size_bytes),
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-i", str(path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=DEVNULL,
                stdout=PIPE,
                stderr=PIPE,
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
            raise MediaProbeUnavailableError(f"{self.binary} is not available") from exc
        except OSError as exc:
            raise MediaProbeUnavailableError("failed to spawn probe process") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except TimeoutError:
            await self._terminate(process)
            raise MediaProbeTimeoutError(f"probe exceeded {self.timeout_seconds}s")

        if process.returncode != 0:
            logger.warning(
                "Media probe returned non-zero exit code",
                extra={"exit_code": process.returncode, "stderr": stderr[:512].decode("utf-8", "replace")},
            )
            raise InvalidMediaError("probe rejected the media file")

        if not stdout:
            raise MediaMetadataUnreadableError("probe returned empty output")

        if len(stdout) > self.max_output_bytes:
            raise MediaMetadataUnreadableError("probe output is too large")

        return stdout

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
            logger.error("Probe process did not exit after kill")


def parse_ffprobe_output(payload: dict[str, Any], *, max_streams: int = 16) -> MediaInfo:
    raw_streams = payload.get("streams")
    if not isinstance(raw_streams, list) or not raw_streams:
        raise InvalidMediaError("media file contains no streams")

    if len(raw_streams) > max_streams:
        raise InvalidMediaError("media file contains too many streams")

    streams = tuple(_parse_stream(index, raw) for index, raw in enumerate(raw_streams))

    raw_format = payload.get("format")
    format_section: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}

    candidates: list[float] = []

    format_duration = _parse_number(format_section.get("duration"), field_name="format.duration")
    if format_duration is not None:
        candidates.append(format_duration)

    for stream, raw in zip(streams, raw_streams, strict=True):
        if stream.is_attached_pic:
            continue
        if stream.duration is not None:
            candidates.append(stream.duration)
        candidates.extend(_tag_durations(raw))

    positive = [value for value in candidates if value > 0]
    if not positive:
        raise MediaMetadataUnreadableError("duration is missing or not positive")

    duration = max(positive)

    format_name = format_section.get("format_name")
    return MediaInfo(
        duration=duration,
        streams=streams,
        format_name=format_name if isinstance(format_name, str) else None,
    )


def _parse_stream(index: int, raw: Any) -> StreamInfo:
    if not isinstance(raw, dict):
        raise MediaMetadataUnreadableError("unexpected stream structure")

    codec_type = raw.get("codec_type")
    if not isinstance(codec_type, str) or not codec_type:
        raise MediaMetadataUnreadableError("stream codec_type is missing")

    disposition = raw.get("disposition")
    attached_pic = bool(disposition.get("attached_pic")) if isinstance(disposition, dict) else False

    stream_index = raw.get("index")
    codec_name = raw.get("codec_name")

    return StreamInfo(
        index=stream_index if isinstance(stream_index, int) else index,
        codec_type=codec_type,
        codec_name=codec_name if isinstance(codec_name, str) else None,
        width=_parse_dimension(raw.get("width"), field_name="stream.width"),
        height=_parse_dimension(raw.get("height"), field_name="stream.height"),
        duration=_parse_number(raw.get("duration"), field_name="stream.duration"),
        frame_rate=_parse_frame_rate(raw.get("avg_frame_rate")) or _parse_frame_rate(raw.get("r_frame_rate")),
        is_attached_pic=attached_pic,
    )


def _is_absent(raw: Any) -> bool:
    if raw is None:
        return True
    return isinstance(raw, str) and raw.strip().lower() in _ABSENT_VALUES


def _parse_number(raw: Any, *, field_name: str) -> float | None:
    if _is_absent(raw):
        return None

    if isinstance(raw, bool):
        raise MediaMetadataUnreadableError(f"{field_name} has invalid type")

    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MediaMetadataUnreadableError(f"{field_name} is not a number") from exc

    if not math.isfinite(value):
        raise MediaMetadataUnreadableError(f"{field_name} is not finite")

    if value < 0:
        raise MediaMetadataUnreadableError(f"{field_name} is negative")

    return value


def _parse_dimension(raw: Any, *, field_name: str) -> int | None:
    value = _parse_number(raw, field_name=field_name)
    if value is None:
        return None
    if not float(value).is_integer():
        raise MediaMetadataUnreadableError(f"{field_name} is not an integer")
    return int(value)


def _parse_frame_rate(raw: Any) -> float | None:
    if _is_absent(raw) or not isinstance(raw, str):
        return None

    numerator, separator, denominator = raw.partition("/")
    if not separator:
        try:
            value = float(raw)
        except ValueError:
            return None
        return value if math.isfinite(value) and value > 0 else None

    try:
        num = float(numerator)
        den = float(denominator)
    except ValueError:
        return None

    if den == 0 or not math.isfinite(num) or not math.isfinite(den):
        return None

    value = num / den
    return value if value > 0 else None


def _tag_durations(raw_stream: dict[str, Any]) -> list[float]:
    tags = raw_stream.get("tags")
    if not isinstance(tags, dict):
        return []

    values: list[float] = []
    for key, value in tags.items():
        if not isinstance(key, str) or key.strip().lower() != "duration":
            continue
        parsed = _parse_timecode(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _parse_timecode(raw: Any) -> float | None:
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text or text.lower() in _ABSENT_VALUES:
        return None

    parts = text.split(":")
    if len(parts) > 3:
        return None

    total = 0.0
    try:
        for part in parts:
            total = total * 60 + float(part)
    except ValueError:
        return None

    if not math.isfinite(total) or total <= 0:
        return None

    return total
