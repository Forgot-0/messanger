"""
Сценарий (b) из промпта: WS fanout latency.

Запуск (отдельно от остальных, п.3 промпта). K читателей = --users Locust'a,
пишущий "писатель" — ОДИН (дословно из промпта: "один 'писатель' шлёт
сообщения"), запускается не как Locust User, а как один фоновый greenlet
с настраиваемой частотой публикации (--writer-rate) — так K (читатели) и
скорость публикации управляются независимо друг от друга:

    locust -f loadtests/locustfiles/ws_fanout.py --host http://app:8000 \\
           --chat-kind supergroup --writer-rate 5 -u 500 -r 50 -t 5m

Прогоните дважды — с --chat-kind group (fanout_on_write, до 500 участников,
см. FAN_OUT_WRITE_THRESHOLD) и с --chat-kind supergroup (active_subscribers) —
как просит промпт, "обе fanout-стратегии" отдельными прогонами.

────────────────────────────────────────────────────────────────────────────
ДВЕ НАХОДКИ ИЗ ПЕРВОГО РЕАЛЬНОГО ПРОГОНА (не из статического чтения кода —
из живого прогона на docker-compose, который показал delivery_fanout_on_read
с нулём сэмплов при 597 успешных отправках и 1000 успешных WS-коннектах).
Обе ниже — БАГИ ПРЕДЫДУЩЕЙ ВЕРСИИ ЭТОГО ФАЙЛА, не приложения; обе исправлены
в текущей версии.

1) `payload["content"]` в событии не существует.

   Предыдущая версия встраивала `lt_sent_at` в `content` сообщения и
   рассчитывала на то, что `payload["content"]` дойдёт до читателя как есть.
   Это было ошибкой: `SendedMessageEvent` (app/chats/models/message.py)
   несёт только `message_id, chat_id, seq, sender_id, message_type` —
   content в доменное событие вообще не попадает, а `build_ws_event`
   (app/chats/dtos/delivery.py) строит `payload` буквально из полей события.
   То есть WS-уведомление о новом сообщении — "тонкое": в нём НЕТ текста
   сообщения вообще, только его id/seq/автор/тип. Это архитектурный факт
   приложения (возможно, намеренный — клиент должен сам дозапросить контент,
   а не полагаться на broadcast), а не баг, который стоит чинить в рамках
   этой задачи — но он ЛОМАЛ измерение, построенное на предположении
   "контент долетит как есть".

   Исправление: писатель после каждого успешного POST кладёт
   `{message_id: sent_at}` в общий (для процесса) словарь
   `environment.loadtest_sent_at` — читатель, получив `new_message`,
   достаёт `payload["message_id"]`, ищет его в этом словаре и считает
   `recv_time - sent_at`. Работает только для НЕ-distributed прогона
   (--master/--worker в одном процессе не окажутся — см. предыдущую
   версию докстринга про NTP; тут дополнительная причина того же вывода:
   без общего процесса словарь не будет общим).

2) Читатели должны занимать РАЗНЫЕ user_id, а не случайные с повторами.

   `WS_MAX_CONNECTIONS_PER_USER=2` (app/chats/config.py). При превышении
   `ChatConnectionManager.register` (app/chats/services/ws.py) не отклоняет
   новое соединение, а молча закрывает САМОЕ СТАРОЕ соединение того же
   user_id (close_code=1012). Предыдущая версия выбирала читателю
   `rng.choice(chat.member_ids)` — то есть С ПОВТОРЕНИЯМИ: при --users,
   заметно превышающем размер супергруппы, многие user_id раздавались
   3+ читателям, и более ранние соединения этих же пользователей просто
   отваливались посреди теста (а код это молча "чинил" реконнектом, без
   единого проваленного request'а в статистике — отсюда и отсутствие
   ошибок при отсутствии данных).

   Исправление: читатели разбираются по member_ids РАВНОМЕРНО (round-robin
   без повторов, пока участников хватает), и при старте теста явно
   проверяется `--users <= 2 * len(chat.member_ids)` — иначе тест
   немедленно завершается с понятной ошибкой вместо тихой деградации.
   Заодно теперь читатель, прежде чем слушать, ЯВНО дожидается
   ws.subscribed/ws.history (loadtests/common/ws_protocol.py) и репортит
   это как отдельный WS-запрос "ws_subscribe" — если сервер пришлёт
   ws.error (в т.ч. из-за конфликта лимита соединений), это будет видно
   в отчёте как failure, а не тихо потеряно.
────────────────────────────────────────────────────────────────────────────

Для сравнения с буквально требуемой промптом формулой (receive_time минус
поле ts, которое, напомним, WSConnection.try_send безусловно перезаписывает
временем постановки в очередь) тест по-прежнему дополнительно репортит
delivery_ts_field_on_write/on_read.

Предположение о синхронизации часов остаётся тем же: писатель и читатели
меряют время через time.time() ОДНОГО процесса — гоняйте без
--master/--worker для честного baseline (см. README).
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from itertools import count
from uuid import uuid4

import gevent
import requests
import websocket
from locust import User, events, task

from loadtests.common.acceptance import Threshold, add_threshold_arg, check_and_report
from loadtests.common.manifest import load_manifest
from loadtests.common.net import synthetic_ip_for_user
from loadtests.common.settings import (
    API_V1_STR,
    HTTP_BASE_URL,
    LOADTEST_MANIFEST_PATH,
    LOADTEST_SPOOF_SOURCE_IP,
)
from loadtests.common.tokens import mint_access_token
from loadtests.common.ws_client import WSClient, build_ws_url
from loadtests.common.ws_protocol import wait_for_subscribe_ack

KEEPALIVE_INTERVAL_S = 25  # < WS_HEARTBEAT_TIMEOUT (75s), см. app/chats/config.py
RECV_POLL_TIMEOUT_S = 20  # редкие пробуждения по таймауту дешевле для gevent-хаба при тысячах читателей
SUBSCRIBE_ACK_TIMEOUT_S = 10.0
SENT_AT_TTL_S = 60.0  # сколько храним {message_id: sent_at} на случай недоставки

FANOUT_NAME_BY_KIND = {
    "group": "delivery_fanout_on_write",
    "supergroup": "delivery_fanout_on_read",
    "channel": "delivery_fanout_on_read",
}
TS_FIELD_NAME_BY_KIND = {
    "group": "delivery_ts_field_on_write",
    "supergroup": "delivery_ts_field_on_read",
    "channel": "delivery_ts_field_on_read",
}
WRITER_REQUEST_NAME = "[writer] POST /chats/{chat_id}/messages/"
SUBSCRIBE_REQUEST_NAME = "ws_subscribe"


@events.init_command_line_parser.add_listener
def _add_args(parser):
    parser.add_argument("--manifest", default=LOADTEST_MANIFEST_PATH, help="Путь к manifest.json от seed.py")
    parser.add_argument(
        "--chat-kind",
        default="supergroup",
        choices=["group", "supergroup", "channel"],
        help="Какую fanout-стратегию гонять: group=fanout_on_write, supergroup/channel=active_subscribers",
    )
    parser.add_argument("--writer-rate", type=float, default=2.0, help="Сообщений в секунду от единственного писателя")

    add_threshold_arg(parser, "--fanout-p95-threshold-ms", 2000.0, "Порог p95 end-to-end delivery latency")
    add_threshold_arg(parser, "--fanout-p99-threshold-ms", 5000.0, "Порог p99 end-to-end delivery latency")
    add_threshold_arg(parser, "--fanout-min-samples", 20.0, "Минимум измерений latency, чтобы порог был осмысленным")


@events.test_start.add_listener
def _setup(environment, **kwargs):
    opts = environment.parsed_options
    manifest = load_manifest(opts.manifest)
    rng = random.Random()
    chat = manifest.random_chat(opts.chat_kind, rng)

    max_readers = 2 * len(chat.member_ids)
    if opts.num_users is not None and opts.num_users > max_readers:
        raise RuntimeError(
            f"--users={opts.num_users} превышает 2×участников выбранного чата "
            f"({len(chat.member_ids)} участников, лимит WS_MAX_CONNECTIONS_PER_USER=2 "
            f"на пользователя → максимум {max_readers} одновременных читателей на этот чат). "
            f"Либо уменьшите --users, либо пересейдите чат покрупнее "
            f"(loadtests/seed.py --supergroup-max-size ...)."
        )

    environment.loadtest_manifest = manifest
    environment.loadtest_chat = chat
    environment.loadtest_stopping = gevent.event.Event()
    environment.loadtest_sent_at = {}  # message_id -> sent_at, пишет только писатель, читает кто угодно
    environment.loadtest_reader_index = count()

    print(
        f"[ws_fanout] цель: chat_id={chat.id} kind={opts.chat_kind} "
        f"members={len(chat.member_ids)} writer_rate={opts.writer_rate}/s "
        f"(лимит читателей на этот чат: {max_readers})"
    )

    environment.loadtest_writer_greenlet = gevent.spawn(_writer_loop, environment, chat, opts)


@events.test_stopping.add_listener
def _stop_writer(environment, **kwargs):
    environment.loadtest_stopping.set()


@events.quitting.add_listener
def _check_acceptance(environment, **kwargs):
    opts = environment.parsed_options
    kind_name = FANOUT_NAME_BY_KIND[opts.chat_kind]
    thresholds = [
        Threshold(f"{kind_name} p95", kind_name, "WS", "p95_ms", opts.fanout_p95_threshold_ms),
        Threshold(f"{kind_name} p99", kind_name, "WS", "p99_ms", opts.fanout_p99_threshold_ms),
        Threshold(f"{kind_name} samples", kind_name, "WS", "min_requests", opts.fanout_min_samples),
    ]
    check_and_report(environment, thresholds)


def _prune_sent_at(sent_at: dict[str, float]) -> None:
    cutoff = time.time() - SENT_AT_TTL_S
    stale = [mid for mid, t in sent_at.items() if t < cutoff]
    for mid in stale:
        sent_at.pop(mid, None)


def _writer_loop(environment, chat, opts) -> None:
    """Единственный писатель. НЕ Locust User — обычный gevent-greenlet с requests.Session,
    репортит свои REST-запросы в статистику Locust вручную (events.request.fire),
    как и требует п.3(b) промпта для WS-измерений."""
    manifest = environment.loadtest_manifest
    writer = manifest.user(chat.owner_id)
    token = mint_access_token(writer.id, writer.username)
    headers = {"Authorization": f"Bearer {token}"}
    if LOADTEST_SPOOF_SOURCE_IP:
        headers["X-Forwarded-For"] = synthetic_ip_for_user(writer.id)

    session = requests.Session()
    url = f"{HTTP_BASE_URL}{API_V1_STR}/chats/{chat.id}/messages/"
    period = 1.0 / max(opts.writer_rate, 0.001)
    sent_at_map = environment.loadtest_sent_at
    tick = 0

    while not environment.loadtest_stopping.is_set():
        started = time.monotonic()
        send_ts = time.time()
        # Содержимое до читателей НЕ долетает (см. докстринг модуля, находка 1) —
        # пишем что-то осмысленное только чтобы REST-ответ было легко узнать в логах.
        body = {"content": f"loadtest {send_ts}"}
        req_headers = {**headers, "Idempotency-Key": str(uuid4())}

        try:
            resp = session.post(url, json=body, headers=req_headers, timeout=10)
            elapsed_ms = (time.monotonic() - started) * 1000
            if resp.status_code == 201:
                message_id = resp.json().get("id")
                if message_id:
                    sent_at_map[message_id] = send_ts
                environment.events.request.fire(
                    request_type="POST", name=WRITER_REQUEST_NAME, response_time=elapsed_ms,
                    response_length=len(resp.content), exception=None, context={},
                )
            else:
                environment.events.request.fire(
                    request_type="POST", name=WRITER_REQUEST_NAME, response_time=elapsed_ms,
                    response_length=0, exception=RuntimeError(f"status={resp.status_code} body={resp.text[:200]!r}"),
                    context={},
                )
        except Exception as exc:  # noqa: BLE001 - репортим любую ошибку транспорта как failure
            elapsed_ms = (time.monotonic() - started) * 1000
            environment.events.request.fire(
                request_type="POST", name=WRITER_REQUEST_NAME, response_time=elapsed_ms,
                response_length=0, exception=exc, context={},
            )

        tick += 1
        if tick % 20 == 0:
            _prune_sent_at(sent_at_map)

        gevent.sleep(max(period - (time.monotonic() - started), 0))


def _parse_ts_field(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


class ReaderUser(User):
    """K читателей на один и тот же chat_id (environment.loadtest_chat), по одному
    строго различному member_id на читателя, пока участников хватает (см. докстринг
    модуля, находка 2) — не rng.choice() с повторами."""

    host = HTTP_BASE_URL
    abstract = False

    def on_start(self) -> None:
        chat = self.environment.loadtest_chat
        manifest = self.environment.loadtest_manifest
        opts = self.environment.parsed_options

        idx = next(self.environment.loadtest_reader_index) % len(chat.member_ids)
        self.user = manifest.user(chat.member_ids[idx])
        self.chat_id = chat.id
        self.fanout_name = FANOUT_NAME_BY_KIND[opts.chat_kind]
        self.ts_field_name = TS_FIELD_NAME_BY_KIND[opts.chat_kind]

        self._connect_and_subscribe(initial=True)

        self._stopping = gevent.event.Event()
        self._recv_greenlet = gevent.spawn(self._recv_loop)
        self._keepalive_greenlet = gevent.spawn(self._keepalive_loop)

    def _connect_and_subscribe(self, initial: bool) -> None:
        token = mint_access_token(self.user.id, self.user.username)
        url = build_ws_url(token, initial_chat_id=self.chat_id, initial_last_seq=0)

        started = time.monotonic()
        try:
            self.client = WSClient(url)
            ok, _next_seq, error_code = wait_for_subscribe_ack(self.client, SUBSCRIBE_ACK_TIMEOUT_S)
        except Exception as exc:
            self.environment.events.request.fire(
                request_type="WS", name=SUBSCRIBE_REQUEST_NAME, response_time=(time.monotonic() - started) * 1000,
                response_length=0, exception=exc, context={},
            )
            if initial:
                raise
            return

        if ok:
            self.environment.events.request.fire(
                request_type="WS", name=SUBSCRIBE_REQUEST_NAME, response_time=(time.monotonic() - started) * 1000,
                response_length=0, exception=None, context={},
            )
        else:
            self.environment.events.request.fire(
                request_type="WS", name=SUBSCRIBE_REQUEST_NAME, response_time=(time.monotonic() - started) * 1000,
                response_length=0, exception=RuntimeError(error_code or "no ack"), context={},
            )
            if initial:
                raise RuntimeError(f"initial subscribe failed: {error_code}")

    def _keepalive_loop(self) -> None:
        while not self._stopping.is_set():
            gevent.sleep(KEEPALIVE_INTERVAL_S)
            try:
                self.client.send_json({"op": "ping"})
            except Exception:
                return

    def _recv_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                frame = self.client.recv_json(timeout=RECV_POLL_TIMEOUT_S)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                if self._stopping.is_set():
                    return
                # Соединение разорвано (в т.ч. возможная эвикция сервером, см.
                # находку 2 в докстринге модуля) — это ДОЛЖНО быть видно в
                # отчёте, а не тихо "починено" реконнектом без следа.
                self.environment.events.request.fire(
                    request_type="WS", name="ws_unexpected_disconnect", response_time=0,
                    response_length=0, exception=RuntimeError("connection lost, reconnecting"), context={},
                )
                self._connect_and_subscribe(initial=False)
                continue

            self._handle_frame(frame)

    def _handle_frame(self, frame: dict) -> None:
        if frame["payload"].get("message") is None:
            return
        recv_time = time.time()

        message_id = frame["payload"]["message"]["id"]

        sent_at = self.environment.loadtest_sent_at.get(message_id) if message_id else None
        if sent_at is not None:
            self.environment.events.request.fire(
                request_type="WS", name=self.fanout_name, response_time=(recv_time - sent_at) * 1000,
                response_length=len(json.dumps(frame)), exception=None, context={},
            )

        ts_value = _parse_ts_field(frame.get("ts"))
        if ts_value is not None:
            self.environment.events.request.fire(
                request_type="WS", name=self.ts_field_name, response_time=(recv_time - ts_value) * 1000,
                response_length=0, exception=None, context={},
            )

    def on_stop(self) -> None:
        self._stopping.set()
        self.client.close()

    @task
    def idle(self) -> None:
        # Вся полезная работа читателя идёт в фоновых greenlet'ах (_recv_loop,
        # _keepalive_loop) — эта task существует только чтобы раннер Locust
        # держал пользователя живым и не считал его "без задач".
        gevent.sleep(1)
