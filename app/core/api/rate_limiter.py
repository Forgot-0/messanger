from fastapi import Request
from fastapi_limiter.depends import RateLimiter
from starlette.responses import Response

from app.core.configs.app import app_config


class ConfigurableRateLimiter(RateLimiter):
    # Можно сделать глабальные настройки для проекта, но пока тут их нет(
    async def __call__(self, request: Request, response: Response) -> None:
        if app_config.RATE_LIMITER_ENABLED:
            await super().__call__(request=request, response=response)
        return
