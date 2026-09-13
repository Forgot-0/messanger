from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
from botocore.config import Config

S3Client = Any

DEFAULT_ADDRESSING_STYLE = "path"
DEFAULT_SIGNATURE_VERSION = "s3v4"


def build_client_config(
    *,
    addressing_style: str = DEFAULT_ADDRESSING_STYLE,
    max_pool_connections: int = 50,
    max_attempts: int = 3,
    connect_timeout: int = 5,
    read_timeout: int = 60,
) -> Config:
    return Config(
        signature_version=DEFAULT_SIGNATURE_VERSION,
        s3={"addressing_style": addressing_style},
        max_pool_connections=max_pool_connections,
        retries={"max_attempts": max_attempts, "mode": "standard"},
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )


@asynccontextmanager
async def s3_client(
    *,
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    region: str,
    config: Config | None = None,
) -> AsyncIterator[S3Client]:
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=config or build_client_config(),
    ) as client: # type: ignore
        yield client
