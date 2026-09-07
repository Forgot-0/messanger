import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProfileEndpoints:

    async def test_create_endpoint(
        self,
        client: AsyncClient,
    ):
        ...
