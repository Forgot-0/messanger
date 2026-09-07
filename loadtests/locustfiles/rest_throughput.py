"""
Сценарий (a) из промпта: REST throughput отправки сообщений.

Запуск (отдельно от остальных сценариев, см. п.3 промпта):
    locust -f loadtests/locustfiles/rest_throughput.py --host http://app:8000

Что меряем: msg/sec и p95/p99 латентность самого REST-ответа — это Locust
даёт "из коробки" через свою статистику по HTTP-запросам (--host, --users,
--spawn-rate, --run-time — стандартные флаги Locust, дополнительно снимать
ничего не нужно, см. п.3(a) промпта).

Каждый виртуальный пользователь (Locust User) при старте:
  1) выбирает случайный чат из --chat-kinds (по умолчанию direct,group,supergroup —
     БЕЗ channel: в канале писать может только owner/staff, обычный участник
     получит 403, так что channel — не про "REST throughput", это отдельный кейс);
  2) выбирает случайного УЧАСТНИКА этого чата и минтит ему токен
     (loadtests/common/tokens.py, тот же JWTManager/UserJWTData, что и в проде);
  3) дальше от его лица шлёт POST .../messages/ в этот чат.

Idempotency-Key: генерируется ЗАНОВО на каждую попытку (см. docstring в
промпте — "ключ уникален на попытку, не на ретрай"), иначе после первого
запроса все последующие с тем же chat_id/user_id полетят в идемпотентный кэш
Redis (chat:idempotency:send:{user_id}:{chat_id}:{key}) и тест будет мерить
скорость чтения из Redis, а не реальную запись сообщений.

IP-rate-limit и X-Forwarded-For: см. loadtests/common/settings.py. Коротко —
message_write_limiter (ConfigurableRateLimiter, RATE_LIMIT_MESSAGES_PER_SECOND=10)
в проде идентифицирует клиента по IP (fastapi_limiter default_identifier:
сначала X-Forwarded-For, потом request.client.host — проверено по
зафиксированной в pyproject.toml версии fastapi_limiter). Если гнать тест без
спуфинга заголовка, ВСЕ виртуальные пользователи из одного локустовского
контейнера долбятся в один и тот же бакет на 10 rps — это не пропускная
способность приложения, а артефакт топологии теста. В проде перед приложением
стоит nginx, который для каждого реального клиента подставляет
X-Forwarded-For (nginx/sites-available, proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for) — therefore спуфинг синтетического
X-Forwarded-For на виртуального пользователя это не обход защиты, а
воспроизведение реальной топологии прод-трафика. Включено по умолчанию
(LOADTEST_SPOOF_SOURCE_IP=1); чтобы вместо этого явно увидеть текущий
IP-bound баг (промпт 1, п.1) — запустите с LOADTEST_SPOOF_SOURCE_IP=0.
"""
from __future__ import annotations

import random
import time
from uuid import uuid4

from locust import HttpUser, between, events, task
from pydantic import ValidationError

from app.chats.dtos.messages import MessageDTO
from loadtests.common.acceptance import Threshold, add_threshold_arg, check_and_report
from loadtests.common.manifest import ChatKind, load_manifest
from loadtests.common.net import synthetic_ip_for_user
from loadtests.common.settings import (
    API_V1_STR,
    HTTP_BASE_URL,
    LOADTEST_MANIFEST_PATH,
    LOADTEST_SPOOF_SOURCE_IP,
)
from loadtests.common.tokens import mint_access_token

REQUEST_NAME = "POST /chats/{chat_id}/messages/"


@events.init_command_line_parser.add_listener
def _add_args(parser):
    parser.add_argument(
        "--chat-kinds",
        default="direct,group,supergroup",
        help="Через запятую: из каких типов чатов случайно выбирать цель (direct,group,supergroup,channel)",
    )
    parser.add_argument("--manifest", default=LOADTEST_MANIFEST_PATH, help="Путь к manifest.json от seed.py")

    add_threshold_arg(parser, "--rest-p95-threshold-ms", 800.0, "Порог p95 латентности REST-отправки")
    add_threshold_arg(parser, "--rest-error-rate-threshold", 0.05, "Порог доли неуспешных отправок (0..1)")
    add_threshold_arg(parser, "--rest-min-requests", 50.0, "Минимум запросов, чтобы порог вообще что-то значил")


@events.test_start.add_listener
def _load_manifest(environment, **kwargs):
    opts = environment.parsed_options
    environment.loadtest_manifest = load_manifest(opts.manifest)
    environment.loadtest_chat_kinds = [k.strip() for k in opts.chat_kinds.split(",") if k.strip()]


@events.quitting.add_listener
def _check_acceptance(environment, **kwargs):
    opts = environment.parsed_options
    thresholds = [
        Threshold("REST send p95", REQUEST_NAME, "POST", "p95_ms", opts.rest_p95_threshold_ms),
        Threshold("REST send error rate", REQUEST_NAME, "POST", "error_rate", opts.rest_error_rate_threshold),
        Threshold("REST send min requests", REQUEST_NAME, "POST", "min_requests", opts.rest_min_requests),
    ]
    check_and_report(environment, thresholds)


class MessageSenderUser(HttpUser):
    host = HTTP_BASE_URL
    wait_time = between(0.05, 0.3)

    def on_start(self) -> None:
        manifest = self.environment.loadtest_manifest
        kinds: list[ChatKind] = self.environment.loadtest_chat_kinds
        rng = random.Random()

        kind = rng.choice(kinds)
        chat = manifest.random_chat(kind, rng)
        if not chat.can_any_member_write:
            # channel: писать может только owner/staff — берём владельца
            self_user_id = chat.owner_id
        else:
            self_user_id = rng.choice(chat.member_ids)

        user = manifest.user(self_user_id)
        self.chat_id = chat.id
        self.token = mint_access_token(user.id, user.username)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        if LOADTEST_SPOOF_SOURCE_IP:
            self.headers["X-Forwarded-For"] = synthetic_ip_for_user(user.id)

    @task
    def send_message(self) -> None:
        idempotency_key = str(uuid4())
        headers = {**self.headers, "Idempotency-Key": idempotency_key}
        body = {"content": f"loadtest {idempotency_key} {time.time()}"}

        with self.client.post(
            f"{API_V1_STR}/chats/{self.chat_id}/messages/",
            json=body,
            headers=headers,
            name=REQUEST_NAME,
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"status={resp.status_code} body={resp.text[:300]!r}")
                return
            try:
                MessageDTO.model_validate_json(resp.text)
            except ValidationError as exc:
                resp.failure(f"ответ 201, но не проходит валидацию MessageDTO: {exc}")
