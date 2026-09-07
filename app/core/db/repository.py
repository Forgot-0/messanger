import hashlib
from abc import ABC
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

import orjson
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.base_model import SoftDeleteMixin
from app.core.db.convertor import SQLAlchemyFilterConverter
from app.core.filters.base import BaseFilter

P = ParamSpec("P")

@dataclass(frozen=True)
class PageResult[T]:
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1


@dataclass
class IRepository[T](ABC):
    session: AsyncSession

    async def find_by_filter(self, model: type[T], filters: BaseFilter) -> PageResult[T]:
        stmt = model.select_not_deleted() if issubclass(model, SoftDeleteMixin) else select(model)

        loading_options = SQLAlchemyFilterConverter.build_loading_options(model, filters.loading_config)

        if loading_options:
            stmt = stmt.options(*loading_options)

        conditions = SQLAlchemyFilterConverter.filter_to_sqlalchemy_conditions(model, filters)

        stmt = self.apply_relationship_filters(stmt, filters)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        sort_clauses = SQLAlchemyFilterConverter.get_sort_attributes(model, filters.sort_fields)
        if sort_clauses:
            stmt = stmt.order_by(*sort_clauses)

        stmt = stmt.offset(filters.pagination.offset).limit(filters.pagination.limit)
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        return PageResult(
            items=list(items),
            total=total,
            page=filters.pagination.page,
            page_size=filters.pagination.page_size
        )

    def apply_relationship_filters(
        self,
        stmt: Select,
        _filters: BaseFilter,
    ) -> Select:
        return stmt

B = TypeVar("B", bound=BaseModel)


@dataclass
class CacheRepository:
    redis: Redis
    _LIST_VERSION_KEY: str = field(kw_only=True, init=False)

    def _serialize_args_kwargs(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
        args_repr = "|".join(repr(a) for a in args)
        kwargs_items = sorted(kwargs.items())
        kwargs_repr = "|".join(f"{k}={v!r}" for k, v in kwargs_items)
        combined = f"args:{args_repr};kwargs:{kwargs_repr}"
        return combined.encode("utf-8")

    async def _build_key(
        self,
        type_model: type[B],
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> str:
        version = await self._get_list_version()

        func_mod = getattr(func, "__module__", "unknown")
        func_qname = getattr(func, "__qualname__", "none")
        serialized = self._serialize_args_kwargs(args, kwargs)
        digest = hashlib.sha256(serialized).hexdigest()
        return f"cache:{type_model.__name__}:ver={version}:{func_mod}.{func_qname}:{digest}"

    async def cache_with_key(
        self,
        key: str,
        type_model: type[B],
        func: Callable[P, Awaitable[B]],
        ttl: int = 60,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> B:
        data = await self.redis.get(key)

        if data is None:
            data_dto = await func(*args, **kwargs)
            cached_data = data_dto.model_dump_json()
            await self.redis.set(key, cached_data, ex=ttl)
            return data_dto

        return type_model.model_validate_json(data)

    async def cache(
        self,
        type_model: type[B],
        func: Callable[P, Awaitable[B]],
        ttl: int = 60,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> B:
        key = await self._build_key(type_model, func, args, kwargs)
        return await self.cache_with_key(
            key, type_model, func, ttl, *args, **kwargs
        )

    async def cache_with_key_paginated(
        self,
        key: str,
        type_model: type[B],
        func: Callable[P, Awaitable[PageResult[B]]],
        ttl: int = 60,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> PageResult[B]:
        data = await self.redis.get(key)

        if data is None:
            data_dto = await func(*args, **kwargs)
            payload = {
                "items": [item.model_dump_json() for item in data_dto.items],
                "total": data_dto.total,
                "page": data_dto.page,
                "page_size": data_dto.page_size
            }
            await self.redis.set(key, value=orjson.dumps(payload), ex=ttl)
            return data_dto

        data = orjson.loads(data)
        return PageResult(
            items=[type_model.model_validate_json(item) for item in data.get("items", [])],
            total=data["total"],
            page=data["page"],
            page_size=data["page_size"]
        )

    async def cache_paginated(
        self, type_model: type[B],
        func: Callable[P, Awaitable[PageResult[B]]],
        ttl: int=60, *args: P.args, **kwargs: P.kwargs,
    ) -> PageResult[B]:
        key = await self._build_key(type_model, func, args, kwargs)
        return await self.cache_with_key_paginated(
            key, type_model, func, ttl, *args, **kwargs
        )

    async def invalidate_cache(self, *keys: str) -> None:
        if keys:
            await self.redis.delete(*keys)
        else:
            await self.redis.incrby(self._LIST_VERSION_KEY)

    async def _get_list_version(self) -> int:
        v = await self.redis.get(self._LIST_VERSION_KEY)
        return int(v) if v else 0

