from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.services.media.dtos import MediaInfo


@dataclass
class MediaProbeService(ABC):

    @abstractmethod
    async def probe(self, path: Path) -> MediaInfo:
        ...
