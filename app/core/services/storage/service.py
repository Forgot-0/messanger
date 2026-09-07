import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.services.storage.dtos import ObjectStat, UploadFile, UploadFilePost, UploadFilePostResponse

clean_filename = re.compile(r"[^\w.\-]")


@dataclass
class StorageService(ABC):
    @abstractmethod
    async def upload_put_url(self, bucket_name: str, file_key: str, expires: int) -> str:
        ...

    @abstractmethod
    async def upload_post_file(self, upload_file_post: UploadFilePost) -> UploadFilePostResponse:
        ...

    @abstractmethod
    async def upload_file(self, upload_file: UploadFile) -> str:
        ...

    @abstractmethod
    async def delete_file(
        self,
        bucket_name: str,
        file_key: str
    ) -> bool:
        ...

    @abstractmethod
    async def generate_presigned_url(
        self,
        bucket_name: str,
        file_key: str,
        expires: int = 3600,
    ) -> str:
        ...

    @abstractmethod
    async def download(self, bucket_name: str, file_key: str) -> bytes:
        ...

    @abstractmethod
    async def download_range(self, bucket_name: str, file_key: str, offset: int, length: int) -> bytes:
        ...

    @abstractmethod
    async def copy_object(
        self, bucket_from: str, file_key_from: str,
        bucket_to: str, file_key_to: str,
        source_stat: ObjectStat | None=None
    ) -> None:
        ...

    @abstractmethod
    async def get_stat(self, bucket_name: str, file_key: str) -> ObjectStat:
        ...

    @abstractmethod
    async def download_to_path(
        self,
        bucket_name: str,
        file_key: str,
        destination: Path,
        *,
        max_bytes: int,
        stat: ObjectStat | None = None,
    ) -> int: ...

    @abstractmethod
    async def download_bytes(
        self,
        bucket_name: str,
        file_key: str,
        *,
        max_bytes: int,
        stat: ObjectStat | None = None,
    ) -> bytes: ...

    @abstractmethod
    def get_public_url_object(self, bucket: str, file_key: str) -> str: ...

    def clean_filename(self, file_name: str, max_len: int = 200) -> str:
        return clean_filename.sub("_", file_name.strip())[:max_len]
