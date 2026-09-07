"""
Настройки для скриптов нагрузочного теста.

Мы намеренно переиспользуем app.core.configs.app.app_config (тот же .env, что и у
приложения) вместо того, чтобы заново парсить POSTGRES_*/JWT_* переменные:
loadtests/ читает секреты и DSN из ТОГО ЖЕ контракта, что и сам app, поэтому не
может "разойтись" с реальной конфигурацией (см. loadtests/README.md, раздел
"Почему Locust и почему так").

Все параметры, специфичные именно для нагрузочного теста (не для приложения),
живут только здесь и читаются из LOADTEST_*-переменных, чтобы не путать их с
конфигурацией приложения.
"""
from __future__ import annotations

import os

from app.core.configs.app import app_config

# ─── HTTP/WS-эндпоинты приложения ────────────────────────────────────────────
# По умолчанию — имя сервиса app в app-network (см. docker-compose.loadtest.yaml).
# Никогда не хардкодим localhost: при желании прогнать тест с хоста (вне
# docker-compose), просто переопределите LOADTEST_HOST=localhost:8000.
LOADTEST_HTTP_HOST: str = os.environ.get("LOADTEST_HOST", "app:8000")
LOADTEST_HTTP_SCHEME: str = os.environ.get("LOADTEST_HTTP_SCHEME", "http")
LOADTEST_WS_SCHEME: str = os.environ.get("LOADTEST_WS_SCHEME", "ws")

HTTP_BASE_URL: str = f"{LOADTEST_HTTP_SCHEME}://{LOADTEST_HTTP_HOST}"
WS_BASE_URL: str = f"{LOADTEST_WS_SCHEME}://{LOADTEST_HTTP_HOST}"

API_V1_STR: str = app_config.API_V1_STR

# ─── Токены ──────────────────────────────────────────────────────────────────
# ACCESS_TOKEN_EXPIRE_MINUTES у приложения (15 минут по умолчанию, см.
# .env.example) рассчитан на реальных пользователей, а не на многочасовой
# прогон нагрузочного теста. Поэтому у loadtest'а СВОЙ, отдельно управляемый
# TTL токена — это единственное намеренное отступление от прод-контракта, и
# оно только увеличивает срок жизни (не меняет формат/подпись токена).
LOADTEST_TOKEN_TTL_MINUTES: int = int(os.environ.get("LOADTEST_TOKEN_TTL_MINUTES", "240"))

# ─── Manifest, созданный loadtests/seed.py ──────────────────────────────────
LOADTEST_MANIFEST_PATH: str = os.environ.get("LOADTEST_MANIFEST_PATH", "/app/loadtests/data/manifest.json")

# ─── Rate limiter (chat_config.RATE_LIMIT_MESSAGES_PER_SECOND) ─────────────
# По умолчанию идентификатор лимитера в приложении — IP клиента
# (fastapi_limiter default_identifier: X-Forwarded-For, иначе request.client.host,
# см. loadtests/README.md, раздел "IP-rate-limit и X-Forwarded-For"). Чтобы
# сценарий REST throughput не мерил "10 rps на всех" (артефакт единственного
# IP локустовского контейнера), каждый виртуальный пользователь по умолчанию
# посылает СВОЙ синтетический X-Forwarded-For — так же, как в проде это делает
# nginx (nginx/sites-available/api.conf: proxy_set_header X-Forwarded-For
# $proxy_add_x_forwarded_for) для каждого реального клиента.
# Установите в "0"/"false", чтобы воспроизвести текущий IP-bound баг как есть
# (все виртуальные пользователи бьются в один и тот же бакет).
LOADTEST_SPOOF_SOURCE_IP: bool = os.environ.get("LOADTEST_SPOOF_SOURCE_IP", "1").lower() not in ("0", "false", "no")
