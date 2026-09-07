import asyncio

import pytest
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.exceptions import IdempotencyConflictError
from app.core.services.idempotency import IdempotencyStore


class Result(BaseModel):
    value: int


@pytest.fixture
def store(redis_client: Redis) -> IdempotencyStore:
    return IdempotencyStore(redis=redis_client)


@pytest.mark.integration
@pytest.mark.core
@pytest.mark.asyncio
class TestIdempotencyStore:
    async def test_without_key_operation_runs_every_time(self, store: IdempotencyStore) -> None:
        calls = 0

        async def operation() -> Result:
            nonlocal calls
            calls += 1
            return Result(value=calls)

        for _ in range(3):
            await store.run(
                scope="test", key=None, owner=(1,), model=Result, operation=operation
            )

        assert calls == 3

    async def test_repeat_with_same_key_returns_first_result(self, store: IdempotencyStore) -> None:
        calls = 0

        async def operation() -> Result:
            nonlocal calls
            calls += 1
            return Result(value=calls)

        first = await store.run(
            scope="test", key="k1", owner=(1, "chat"), model=Result, operation=operation
        )
        second = await store.run(
            scope="test", key="k1", owner=(1, "chat"), model=Result, operation=operation
        )

        assert first.value == second.value == 1
        assert calls == 1

    async def test_different_owners_do_not_share_the_key(self, store: IdempotencyStore) -> None:
        async def operation_for(value: int):
            async def _operation() -> Result:
                return Result(value=value)

            return _operation

        first = await store.run(
            scope="test", key="k1", owner=(1,), model=Result, operation=await operation_for(1)
        )
        second = await store.run(
            scope="test", key="k1", owner=(2,), model=Result, operation=await operation_for(2)
        )

        assert (first.value, second.value) == (1, 2)

    async def test_parallel_retry_gets_conflict_instead_of_second_write(
        self, store: IdempotencyStore
    ) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def slow_operation() -> Result:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return Result(value=calls)

        async def fast_operation() -> Result:
            nonlocal calls
            calls += 1
            return Result(value=calls)

        first = asyncio.create_task(
            store.run(scope="test", key="k2", owner=(1,), model=Result, operation=slow_operation)
        )
        await started.wait()

        with pytest.raises(IdempotencyConflictError):
            await store.run(
                scope="test", key="k2", owner=(1,), model=Result, operation=fast_operation
            )

        release.set()
        await first

        assert calls == 1

    async def test_failed_operation_does_not_leave_the_lock(self, store: IdempotencyStore) -> None:
        async def failing() -> Result:
            raise RuntimeError("boom")

        async def succeeding() -> Result:
            return Result(value=7)

        with pytest.raises(RuntimeError):
            await store.run(
                scope="test", key="k3", owner=(1,), model=Result, operation=failing
            )

        retried = await store.run(
            scope="test", key="k3", owner=(1,), model=Result, operation=succeeding
        )
        assert retried.value == 7
