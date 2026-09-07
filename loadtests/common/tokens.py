"""
Минтинг access-токенов для виртуальных пользователей нагрузочного теста.

Пункт 1 промпта прямо требует не дублировать контракт токена на другом языке/
вручную, а переиспользовать app.core.services.auth.jwt_manager.JWTManager и
app.core.services.auth.dto.UserJWTData — тот же код, которым приложение и само
подписывает/валидирует токены (см. tests/conftest.py::create_access_token,
тот же паттерн). Мы намеренно НЕ используем app.auth.services.jwt.AuthJWTManager
целиком: он тянет за собой TokenBlacklistRepository (Redis) и жёстко зашитый
auth_config.ACCESS_TOKEN_EXPIRE_MINUTES (15 минут в проде) — неподходящий TTL
для многочасового прогона теста. Вместо этого мы вручную собираем payload той
же формы (см. AuthJWTManager.generate_payload) и подписываем его тем же
JWTManager.encode(), так что итоговый токен неотличим от настоящего для
get_ws_access_token / CurrentUserJWTData.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.jwt_manager import JWTManager
from app.core.utils import now_utc

from loadtests.common.settings import LOADTEST_TOKEN_TTL_MINUTES

_jwt_manager = JWTManager()

# Роль/security level соответствуют RolesEnum.STANDARD_USER
# (app/auth/models/role_permission.py) — обычный зарегистрированный пользователь,
# без дополнительных permissions. Именно эту роль присваивает seed.py.
STANDARD_USER_ROLES: list[str] = ["user"]
STANDARD_USER_SECURITY_LEVEL: int = 1


@dataclass(frozen=True, slots=True)
class MintedUser:
    user_id: int
    username: str
    token: str


def mint_access_token(user_id: int, username: str, device_id: str | None = None) -> str:
    """Собрать и подписать access-токен для существующего (посеянного) пользователя."""
    user_jwt_data = UserJWTData(
        id=str(user_id),
        username=username,
        roles=STANDARD_USER_ROLES,
        permissions=[],
        security_level=STANDARD_USER_SECURITY_LEVEL,
        device_id=device_id or f"loadtest-{user_id}",
    )

    now = now_utc()
    payload: dict[str, Any] = {
        "type": "access",
        "jti": str(uuid4()),
        "exp": (now + timedelta(minutes=LOADTEST_TOKEN_TTL_MINUTES)).timestamp(),
        "iat": now.timestamp(),
        **user_jwt_data.to_dict(),
    }
    return _jwt_manager.encode(payload)


def mint_user(user_id: int, username: str, device_id: str | None = None) -> MintedUser:
    return MintedUser(
        user_id=user_id,
        username=username,
        token=mint_access_token(user_id, username, device_id=device_id),
    )
