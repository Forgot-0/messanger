"""
Сценарий (c) из промпта: WS connection churn + resume.

Массово переподключаемся (закрыть/открыть, resume с курсором) и смотрим,
деградирует ли delivery router/Redis по клиентским latency/error rate —
БЕЗ обращения к внутренним метрикам (только то, что видно из клиента).

Запуск (отдельно от остальных, п.3 промпта):
    locust -f loadtests/locustfiles/ws_churn.py --host http://app:8000 \\
           --churn-rate 5 -u 200 -r 20 -t 5m

Rate-limit на resume/subscribe (п.3(c) промпта): на момент написания теста
серверного лимита на WS-командах ЕЩЁ НЕТ (промпт 1, п.4 не выполнен — grep по
app/ не находит RATE_LIMITED в WS-пути). Поэтому --churn-rate — это
КЛИЕНТСКИЙ token bucket (loadtests/common/rate_limiter.py), общий на все
виртуальные пользователи сценария, ограничивающий суммарную частоту
subscribe/resume-команд. Если/когда промпт 1 будет выполнен, увеличьте
--churn-rate выше серверного лимита — тогда тест начнёт честно измерять
поведение приложения под RATE_LIMITED, а не собственный клиентский потолок
(см. loadtests/README.md).

WS_MAX_CONNECTIONS_PER_USER=2 (app/chats/config.py) — та же находка, что и
в ws_fanout.py (см. его докстринг): при 3+ конкурентных соединениях одного
user_id сервер молча закрывает САМОЕ СТАРОЕ. Для churn-сценария это не
обязательно "баг измерения" (много переподключений с одним user_id — тоже
реалистичный кейс, "два устройства одного аккаунта"), но чтобы не путать
самонаведённые коллизии с реальной деградацией сервера, читатели внутри
ОДНОГО чата разбираются round-robin по его участникам (а не rng.choice()
с повторами) — см. _next_member_id. Если --users на чат всё равно больше
2×участников, это осознанный выбор нагрузки, а не случайность.
"""
from __future__ import annotations

import random
import time
from collections import defaultdict
from itertools import count

import gevent
from locust import User, constant, events, task

from loadtests.common.acceptance import Threshold, add_threshold_arg, check_and_report
from loadtests.common.manifest import load_manifest
from loadtests.common.rate_limiter import TokenBucket
from loadtests.common.settings import HTTP_BASE_URL, LOADTEST_MANIFEST_PATH
from loadtests.common.tokens import mint_access_token
from loadtests.common.ws_client import WSClient, build_ws_url
from loadtests.common.ws_protocol import wait_for_subscribe_ack

ACK_TIMEOUT_S = 10.0

CONNECT_SUBSCRIBE_NAME = "ws_connect_subscribe"
RESUME_NAME = "ws_resume"


@events.init_command_line_parser.add_listener
def _add_args(parser):
    parser.add_argument("--manifest", default=LOADTEST_MANIFEST_PATH, help="Путь к manifest.json от seed.py")
    parser.add_argument(
        "--chat-kinds", default="group,supergroup",
        help="Через запятую: из каких типов чатов выбирать цель для churn (direct,group,supergroup,channel)",
    )
    parser.add_argument(
        "--churn-rate", type=float, default=5.0,
        help="Максимум subscribe+resume команд в секунду СУММАРНО по всем виртуальным пользователям "
             "(клиентский self-throttle, см. docstring модуля)",
    )
    parser.add_argument("--hold-min-s", type=float, default=1.0, help="Мин. время удержания соединения открытым")
    parser.add_argument("--hold-max-s", type=float, default=5.0, help="Макс. время удержания соединения открытым")
    parser.add_argument("--reconnect-gap-min-s", type=float, default=0.1)
    parser.add_argument("--reconnect-gap-max-s", type=float, default=1.0)

    add_threshold_arg(parser, "--churn-p95-threshold-ms", 1500.0, "Порог p95 латентности subscribe/resume ack")
    add_threshold_arg(parser, "--churn-error-rate-threshold", 0.05, "Порог доли неуспешных subscribe/resume (0..1)")
    add_threshold_arg(parser, "--churn-min-requests", 50.0, "Минимум циклов churn, чтобы порог был осмысленным")


@events.test_start.add_listener
def _setup(environment, **kwargs):
    opts = environment.parsed_options
    environment.loadtest_manifest = load_manifest(opts.manifest)
    environment.loadtest_chat_kinds = [k.strip() for k in opts.chat_kinds.split(",") if k.strip()]
    environment.loadtest_bucket = TokenBucket(opts.churn_rate, burst=max(1, int(opts.churn_rate)))
    environment.loadtest_member_index_by_chat = defaultdict(count)


@events.quitting.add_listener
def _check_acceptance(environment, **kwargs):
    opts = environment.parsed_options
    thresholds = [
        Threshold("WS connect+subscribe p95", CONNECT_SUBSCRIBE_NAME, "WS", "p95_ms", opts.churn_p95_threshold_ms),
        Threshold("WS connect+subscribe error rate", CONNECT_SUBSCRIBE_NAME, "WS", "error_rate", opts.churn_error_rate_threshold),
        Threshold("WS resume p95", RESUME_NAME, "WS", "p95_ms", opts.churn_p95_threshold_ms),
        Threshold("WS resume error rate", RESUME_NAME, "WS", "error_rate", opts.churn_error_rate_threshold),
        Threshold("WS churn min cycles", CONNECT_SUBSCRIBE_NAME, "WS", "min_requests", opts.churn_min_requests),
    ]
    check_and_report(environment, thresholds)


def _fire(environment, name: str, started: float, exception: Exception | None) -> None:
    environment.events.request.fire(
        request_type="WS",
        name=name,
        response_time=(time.monotonic() - started) * 1000,
        response_length=0,
        exception=exception,
        context={},
    )


def _next_member_id(environment, chat) -> int:
    """Round-robin по участникам ЭТОГО чата — см. докстринг модуля про
    WS_MAX_CONNECTIONS_PER_USER=2 и самонаведённые коллизии."""
    idx = next(environment.loadtest_member_index_by_chat[chat.id])
    return chat.member_ids[idx % len(chat.member_ids)]


class ChurnUser(User):
    host = HTTP_BASE_URL
    wait_time = constant(0)  # темп задаём сами внутри task через явные sleep
    abstract = False

    def on_start(self) -> None:
        manifest = self.environment.loadtest_manifest
        kinds = self.environment.loadtest_chat_kinds
        rng = random.Random()

        kind = rng.choice(kinds)
        chat = manifest.random_chat(kind, rng)
        self.chat = chat
        self.user = manifest.user(_next_member_id(self.environment, chat))
        self.last_seq = 0
        self.rng = rng

    @task
    def churn_cycle(self) -> None:
        env = self.environment
        opts = env.parsed_options

        env.loadtest_bucket.acquire()
        started = time.monotonic()
        token = mint_access_token(self.user.id, self.user.username)
        url = build_ws_url(token, initial_chat_id=self.chat.id, initial_last_seq=self.last_seq)

        try:
            client = WSClient(url)
        except Exception as exc:
            _fire(env, CONNECT_SUBSCRIBE_NAME, started, exc)
            gevent.sleep(self.rng.uniform(opts.reconnect_gap_min_s, opts.reconnect_gap_max_s))
            return

        ok, next_seq, error_code = wait_for_subscribe_ack(client, ACK_TIMEOUT_S)
        if ok:
            _fire(env, CONNECT_SUBSCRIBE_NAME, started, None)
            if next_seq is not None:
                self.last_seq = next_seq
        else:
            _fire(env, CONNECT_SUBSCRIBE_NAME, started, RuntimeError(error_code or "no ack"))
            client.close()
            gevent.sleep(self.rng.uniform(opts.reconnect_gap_min_s, opts.reconnect_gap_max_s))
            return

        gevent.sleep(self.rng.uniform(opts.hold_min_s, opts.hold_max_s))

        env.loadtest_bucket.acquire()
        resume_started = time.monotonic()
        try:
            client.send_json({"op": "resume", "cursors": {self.chat.id: self.last_seq}})
            ok, next_seq, error_code = wait_for_subscribe_ack(client, ACK_TIMEOUT_S)
        except Exception as exc:
            ok, next_seq, error_code = False, None, str(exc)

        if ok:
            _fire(env, RESUME_NAME, resume_started, None)
            if next_seq is not None:
                self.last_seq = next_seq
        else:
            _fire(env, RESUME_NAME, resume_started, RuntimeError(error_code or "no ack"))

        client.close()
        gevent.sleep(self.rng.uniform(opts.reconnect_gap_min_s, opts.reconnect_gap_max_s))
