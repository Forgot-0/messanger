from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.services.media.dtos import HlsJob, MediaInfo


@dataclass
class MediaProbeService(ABC):

    @abstractmethod
    async def probe(self, path: Path) -> MediaInfo:
        ...


@dataclass
class MediaTranscoder(ABC):

    @abstractmethod
    async def decode_image(self, source: Path, destination: Path, *, max_pixels: int) -> None:
        ...

    @abstractmethod
    async def extract_frame(
        self, source: Path, destination: Path, *, offset_seconds: float, max_side: int, hdr: bool
    ) -> None:
        ...

    @abstractmethod
    async def strip_metadata(self, source: Path, destination: Path, *, container: str) -> None:
        ...

    @abstractmethod
    async def transcode_hls(self, source: Path, output_dir: Path, job: HlsJob) -> None:
        ...
