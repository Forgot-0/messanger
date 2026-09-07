from dataclasses import dataclass

from app.core.exceptions import ApplicationError


@dataclass(kw_only=True)
class StorageError(ApplicationError):
    code: str = "STORAGE_UNKNOW_ERROR"
    status: int = 500


@dataclass(kw_only=True)
class ObjectNotFoundError(StorageError):
    bucket_name: str
    file_key: str
    code: str = "STORAGE_OBJECT_NOT_FOUND"
    status: int = 500


    @property
    def message(self) -> str:
        return f"Object not found in bucket {self.bucket_name!r}"


@dataclass(kw_only=True)
class ObjectChangedError(StorageError):
    bucket_name: str
    file_key: str

    code: str = "STORAGE_OBJECT_CHANGE"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Object changed during processing in bucket {self.bucket_name!r}"


@dataclass(kw_only=True)
class ObjectTooLargeError(StorageError):
    bucket_name: str
    file_key: str
    max_bytes: int

    code: str = "STORAGE_OBJECT_TOO_LARGE"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Object exceeds allowed size of {self.max_bytes} bytes"
