from fastapi import HTTPException, Request
from fastapi_limiter.depends import RateLimiter
from starlette.responses import Response

from app.core.configs.app import app_config
from app.core.exceptions import RateLimitError


class ConfigurableRateLimiter(RateLimiter):
    # Можно сделать глабальные настройки для проекта, но пока тут их нет(
    async def __call__(self, request: Request, response: Response) -> None:
        if app_config.RATE_LIMITER_ENABLED:
            try:
                await super().__call__(request=request, response=response)
            except HTTPException as ex:
                raise RateLimitError(
                    expire=ex.headers.get("Retry-After", "0") if ex.headers else "0"
                )
        return
