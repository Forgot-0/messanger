# Нагрузочный тест app/chats

Baseline-измерение msg/sec, WS fanout latency (p50/p95/p99) и поведения под
перегрузкой для `app/chats`, без каких-либо изменений в наблюдаемости
приложения — все цифры снимаются исключительно средствами Locust (его
собственная статистика по запросам: response_time percentiles, fail count,
num_requests). Ни одна метрика, Gauge/Histogram, файл `app/consumers.py`,
`app/core/outbox/metrics.py` и т.п. не менялись.

> **Статус:** код прогнан вживую на реальном docker-compose стенде (не только
> статически). Первый живой прогон `ws_fanout.py --chat-kind supergroup`
> вскрыл два реальных бага в ПРЕДЫДУЩЕЙ версии теста (не в приложении) —
> `delivery_fanout_on_read` показывал 0 сэмплов при 597 успешных отправках и
> 1000 успешных WS-коннектах. Оба исправлены и локально перепроверены на
> протокольно точном fake-сервере (см.
> ["Находки, изменившие дизайн теста"](#находки-изменившие-дизайн-теста),
> пункты "`payload` не содержит `content`" и "читатели должны занимать разные
> user_id"). Раздел ["Baseline-числа"](#baseline-числа-первый-прогон) ниже
> по-прежнему пуст — впишите туда цифры первого прогона С ИСПРАВЛЕННОЙ
> версией на своём стенде.


## Оглавление

- [Почему Locust и почему так](#почему-locust-и-почему-так)
- [Находки, изменившие дизайн теста](#находки-изменившие-дизайн-теста)
- [Структура](#структура)
- [Как запустить](#как-запустить)
- [Acceptance-критерии](#acceptance-критерии)
- [Baseline-числа (первый прогон)](#baseline-числа-первый-прогон)
- [Что дальше](#что-дальше)

## Почему Locust и почему так

Locust (Python), а не k6: `loadtests/` напрямую импортирует
`app.core.services.auth.jwt_manager.JWTManager` и
`app.core.services.auth.dto.UserJWTData` для минтинга токенов
(`loadtests/common/tokens.py`) и `app.chats.dtos.messages.MessageDTO` для
валидации ответов REST (`loadtests/locustfiles/rest_throughput.py`) — тот же
код, которым подписывает токены и сериализует ответы само приложение. Это
исключает целый класс ошибок теста "токен/контракт из теста не совпадает с
тем, что реально проверяет prod-код" — на k6 пришлось бы либо переносить
формат JWT-пейлоада и Pydantic-схемы на JS вручную (и они неизбежно
разойдутся при следующем PR), либо минтить токены отдельным Python-скриптом
заранее, что не годится для сценариев с десятками тысяч виртуальных
пользователей (нужно минтить токен на лету при коннекте, а не заранее одним
файлом).

Плата за это: `loadtests/Dockerfile` — не обвязка над официальным образом
locust, а собственный build (см. сам файл, он в деталях объясняет, зачем это
именно так), который переиспользует `pyproject.toml`/`poetry.lock`
приложения (те же версии asyncpg/pydantic/sqlalchemy) и добавляет поверх
только `locust`+`websocket-client` (`loadtests/requirements.txt`). Ни
`Dockerfile` приложения, ни `pyproject.toml`, ни `poetry.lock` не менялись —
`loadtests/Dockerfile` их только читает.

`loadtests/` — новая директория верхнего уровня, не `tests/`: это не pytest,
не должно попадать в обычный test discovery/CI unit-прогон.

## Находки, изменившие дизайн теста

Всё найдено при проектировании теста (чтение исходников, на которые тест
опирается), не при реальном прогоне — реальный прогон мог бы вскрыть больше.
Ничего из перечисленного НЕ исправлено в рамках этой задачи (см. постановку:
"не оптимизируй код... только измерь и задокументируй") — каждый пункт ниже
это готовая заявка на отдельный промпт.

### `ts` в `ws.new_message` — не то, чем кажется

Промпт предполагал мерить delivery latency как `receive_time - payload["ts"]`
(поле "уже есть в payload — `build_ws_event`"). Это верно только наполовину:
`build_ws_event` (`app/chats/dtos/delivery.py`) действительно кладёт
`ts = event["created_at"]` — время исходного доменного события. Но
`WSConnection.try_send()` (`app/chats/dtos/websocket.py`) **безусловно
перезаписывает** `event["ts"] = now_utc().isoformat()` прямо перед
постановкой в очередь на отправку конкретному сокету — то есть ко времени,
когда фрейм уходит по проводу, `ts` уже не содержит исходное время события,
а содержит момент постановки в очередь у конкретного gateway, **уже после**
Kafka + delivery router + Redis lookup. `receive_time - ts` в текущем виде
меряет только "хвост" пути (постановка в очередь → сокет → сеть → клиент),
а не end-to-end fanout latency.

Тест обходит это не правкой приложения (это отдельный промпт), а тем, что
сам встраивает временную метку отправки в `content` сообщения
(`{"lt_sent_at": ..., "lt_msg_id": ...}`, см. `loadtests/locustfiles/ws_fanout.py`)
и меряет `receive_time - lt_sent_at` — честный client-to-client end-to-end
delivery latency, репортится под именами `delivery_fanout_on_write`/
`delivery_fanout_on_read`, как и просит п.3(b) промпта. Дополнительно, только
для количественной иллюстрации масштаба бага, репортится **и** буквально
требуемая промптом формула через сломанное поле `ts`, под именами
`delivery_ts_field_on_write`/`delivery_ts_field_on_read` — разница между
этими двумя парами чисел в отчёте Locust наглядно покажет, сколько latency
"теряется" из вида из-за перезаписи `ts`.

### Rate limiter на REST send — по IP, не по пользователю

`message_write_limiter` (`ConfigurableRateLimiter`, `RATE_LIMIT_MESSAGES_PER_SECOND=10`,
`app/chats/routes/v1/messages.py`) идентифицирует клиента через
`fastapi_limiter`'s `default_identifier`, который смотрит на
`X-Forwarded-For`, а если его нет — на `request.client.host` (проверено по
исходнику зафиксированной в `pyproject.toml` версии `fastapi-limiter`). В
проде перед приложением стоит nginx, который для каждого реального клиента
подставляет `X-Forwarded-For` (`nginx/sites-available/*.conf`:
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`) — так что в
проде лимит действительно ~per-client (с оговоркой про NAT/корпоративные
прокси — вероятно, как раз то, что чинит отдельный промпт 1, п.1).

Если гонять `rest_throughput.py`/писателя `ws_fanout.py` из одного
локустовского контейнера БЕЗ подмены заголовка, все виртуальные
пользователи бьются в один и тот же IP-бакет на 10 rps — и тест "измерил"
бы не пропускную способность приложения, а этот артефакт топологии. Поэтому
по умолчанию (`LOADTEST_SPOOF_SOURCE_IP=1`) каждый виртуальный пользователь
шлёт свой синтетический `X-Forwarded-For` (`loadtests/common/net.py`,
детерминированно из `user_id`) — это не обход защиты, а воспроизведение
той же топологии, что и в проде. Хотите явно увидеть текущий IP-bound баг
как есть — `LOADTEST_SPOOF_SOURCE_IP=0`.

### `GROUP` физически не может достичь `ACTIVE_SUBSCRIBERS`

`Chat.fanout_strategy` переключает `GROUP` на `ACTIVE_SUBSCRIBERS`, только
если `member_count > FAN_OUT_WRITE_THRESHOLD` (500), но
`Chat.member_limit(GROUP) == chat_config.MAX_GROUP_MEMBERS == 500` — то есть
у обычной группы физически не может быть больше 500 участников, а условие
требует строго больше 500. Эта ветка в `fanout_strategy` для `GROUP`
недостижима. Поэтому тест проверяет `ACTIVE_SUBSCRIBERS` только через
`SUPERGROUP` (`MAX_SUPERGROUP_MEMBERS=1_000_000`) — семантически это и есть
"обе fanout-стратегии", которые просит промпт, но `--chat-kinds` теста этого
не подразумевает "переросшая группа", а именно `supergroup`.

### Пассивный WS-читатель отвалится по heartbeat, если молчит

`ChatConnectionManager` разрывает соединение по
`WS_HEARTBEAT_TIMEOUT=75s` бездействия (`last_seen_at` обновляется только
`conn.touch()`, который вызывается лишь при получении **любого** клиентского
фрейма). Читатель сценария (b), который только слушает и ничего не
отправляет, был бы принудительно отключён примерно через 75 секунд.
`ReaderUser` в `ws_fanout.py` поэтому шлёт `{"op":"ping"}` каждые 25с
(`KEEPALIVE_INTERVAL_S`, с запасом относительно `WS_HEARTBEAT_INTERVAL=30s`,
который сервер присылает клиенту в `ws.ready`).

### `WS_MAX_CONNECTIONS_PER_USER=2`

У одного `user_id` не может быть больше 2 одновременных WS-соединений
(`app/chats/config.py`). Поэтому "K читателей" в сценарии (b) — это K
**разных** посеянных пользователей-участников чата, а не K соединений от
одного и того же пользователя; `seed.py` создаёт супергруппы/группы с
достаточным запасом участников для этого.

### `payload` в `ws.new_message` не содержит `content` — событие "тонкое"

Обнаружено живым прогоном (`delivery_fanout_on_read` = 0 сэмплов при 597
успешных отправках), не статическим чтением кода — предыдущая версия теста
предполагала, что `payload["content"]` дойдёт до читателя, и встраивала туда
временную метку для замера honest end-to-end latency. Это было неверно:
`SendedMessageEvent` (`app/chats/models/message.py`) несёт только
`message_id, chat_id, seq, sender_id, message_type` — контента в доменном
событии просто нет, и `build_ws_event` (`app/chats/dtos/delivery.py`) строит
`payload` буквально из полей события. WS-уведомление о новом сообщении —
тонкое: клиент, получив его, не видит текста, только id/seq/автора/тип, и
должен бы (в реальном клиенте) дозапрашивать содержимое отдельно. Это факт
архитектуры приложения (возможно, намеренный), но он ломал предыдущую версию
измерения. Исправлено: `ws_fanout.py` теперь коррелирует по `message_id`
через словарь `{message_id: sent_at}`, который пишет писатель сразу после
201-го ответа (там `id` реального сообщения есть) — общий на процесс, не
per-connection.

### Читателей нельзя раздавать со `rng.choice()` — `WS_MAX_CONNECTIONS_PER_USER=2` эвиктит СТАРОЕ соединение

Тоже обнаружено живым прогоном. `ChatConnectionManager.register`
(`app/chats/services/ws.py`) при превышении лимита в 2 одновременных
соединения на `user_id` не отклоняет НОВОЕ соединение — он молча закрывает
САМОЕ СТАРОЕ (`close_code=1012`). Предыдущая версия `ws_fanout.py` выбирала
читателю `rng.choice(chat.member_ids)` — с повторами. При `--users`, заметно
превышающем размер супергруппы (как в первом прогоне: 1000 читателей против
меньшего числа участников), многие `user_id` доставались 3+ читателям, и
более ранние соединения этих же пользователей отваливались посреди теста —
без единого проваленного запроса в статистике, потому что реконнект "тихо
чинил" симптом, ничего не репортя. Исправлено: читатели теперь разбираются
по `member_ids` round-robin (по одному различному участнику на читателя,
пока хватает), при старте теста явно проверяется
`--users <= 2 × len(участников)` (иначе `RuntimeError` с понятным текстом
вместо тихой деградации), и добавлено явное ожидание `ws.subscribed`/
`ws.history` (`loadtests/common/ws_protocol.py`) с репортингом как
отдельного WS-запроса `ws_subscribe` — если сервер всё же пришлёт
`ws.error`, это будет видно как failure, а не потеряно молча. Неожиданный
разрыв уже установленного соединения тоже теперь репортится отдельным
failure-событием `ws_unexpected_disconnect` перед попыткой переподключения.

### `RATE_LIMITER_ENABLED` — мёртвый флаг

`app_config.RATE_LIMITER_ENABLED` объявлен (`app/core/configs/app.py`), но
нигде в коде не читается — переключить лимитер через `.env` невозможно, флаг
ни на что не влияет. Не блокирует эту задачу (мы и не пытаемся отключать
лимитер), но стоит зафиксировать как мелкую находку для отдельного промпта.

## Структура

```
loadtests/
├── README.md                      # этот файл
├── Dockerfile                     # см. "Почему Locust и почему так"
├── requirements.txt                # locust + websocket-client поверх venv приложения
├── seed.py                         # п.2 промпта: сидинг пользователей/чатов
├── common/
│   ├── settings.py                 # HTTP/WS base url, TTL токенов, спуфинг IP — из ENV
│   ├── tokens.py                   # минтинг JWT через JWTManager/UserJWTData приложения
│   ├── manifest.py                 # чтение manifest.json, который пишет seed.py
│   ├── ws_client.py                 # тонкая обёртка над websocket-client под протокол ws.py
│   ├── ws_protocol.py               # ожидание ws.subscribed/ws.history-ack (ws_fanout.py + ws_churn.py)
│   ├── net.py                      # синтетический X-Forwarded-For на пользователя
│   ├── rate_limiter.py             # клиентский token bucket для сценария (c)
│   └── acceptance.py               # acceptance-критерии как код, поверх Locust stats API
└── locustfiles/
    ├── rest_throughput.py          # сценарий (a)
    ├── ws_fanout.py                 # сценарий (b)
    └── ws_churn.py                  # сценарий (c)

docker-compose.loadtest.yaml        # п.5 промпта
```

Каждый сценарий — самостоятельный `locustfile`, гоняется независимо от
остальных (`locust -f loadtests/locustfiles/<файл>.py ...`), как и просит
п.3 промпта.

## Как запустить

Через `docker compose` (рекомендуемый способ — гарантирует те же имена
сервисов в сети, что и у `app`/`consumers`, без `localhost`):

```bash
# 1. Собрать образ теста (переиспользует pyproject.toml/poetry.lock приложения)
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml build loadtest-seed

# 2. Поднять сам стенд (без бесконечных restart-сервисов очередей/scheduler — не нужны для теста)
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml up -d --build \
    db redis kafka minio debezium debezium_connector app consumers

# 3. Прогнать миграции + init_data (роли/chat_roles — без них seed.py упадёт с понятной ошибкой)
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm migrations

# 4. Засеять данные (N/M/K и размеры — все аргументы командной строки, п.2 промпта)
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm loadtest-seed \
    --users 6000 --direct-chats 1500 --group-chats 2000 --supergroups 6 --channels 2

# 5a. Сценарий (a): REST throughput
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm \
    -e LOCUST_USERS=200 -e LOCUST_SPAWN_RATE=20 -e LOCUST_RUN_TIME=5m \
    loadtest-rest-throughput

# 5b. Сценарий (b): WS fanout latency — прогнать ОБА варианта отдельно
# ВАЖНО: --users не может превышать 2×(число участников выбранного чата) —
# тест сам это проверит при старте и упадёт с понятной ошибкой, если
# засеянная супергруппа слишком мала для запрошенного числа читателей
# (см. "Находки" — WS_MAX_CONNECTIONS_PER_USER=2).
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm \
    -e LOCUST_CHAT_KIND=group -e LOCUST_USERS=400 -e LOCUST_WRITER_RATE=2 -e LOCUST_RUN_TIME=5m \
    loadtest-ws-fanout
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm \
    -e LOCUST_CHAT_KIND=supergroup -e LOCUST_USERS=1000 -e LOCUST_WRITER_RATE=5 -e LOCUST_RUN_TIME=5m \
    loadtest-ws-fanout

# 5c. Сценарий (c): WS connection churn + resume
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm \
    -e LOCUST_USERS=200 -e LOCUST_CHURN_RATE=5 -e LOCUST_RUN_TIME=5m \
    loadtest-ws-churn

# Уборка данных теста (по манифесту — трогает ТОЛЬКО то, что засеял seed.py)
docker compose -f docker-compose.yaml -f docker-compose.loadtest.yaml run --rm loadtest-seed \
    -- --cleanup
```

Locust понимает свои опции (и любые кастомные, добавленные через
`init_command_line_parser`, включая пороги acceptance-критериев) и через
переменные окружения `LOCUST_<ИМЯ_ФЛАГА>` — `docker-compose.loadtest.yaml`
уже задаёт разумные дефолты, их не обязательно передавать явно.

Локально (без Docker), если стенд поднят через `docker compose` и порт 8000
проброшен на хост (как в базовом `docker-compose.yaml`):

```bash
pip install -r loadtests/requirements.txt
LOADTEST_HOST=localhost:8000 LOADTEST_MANIFEST_PATH=./loadtests/data/manifest.json \
    python loadtests/seed.py --users 500 --direct-chats 100 --group-chats 10 --supergroups 2
LOADTEST_HOST=localhost:8000 locust -f loadtests/locustfiles/rest_throughput.py \
    --manifest ./loadtests/data/manifest.json --headless -u 50 -r 10 -t 2m
```

(В этом режиме нужен полноценный Python-env приложения — `poetry install`
из корня репозитория — так как `loadtests/` импортирует `app.*`.)

## Acceptance-критерии

Каждый сценарий сам решает, провалился прогон или нет (`loadtests/common/acceptance.py`),
основываясь **только** на `environment.stats` самого Locust (response_time
percentiles, `num_failures`/`num_requests`) — никаких внешних метрик.
Пороги — CLI-параметры (`LOCUST_<ИМЯ>`), не константы в коде:

| Сценарий | Порог | Дефолт | Флаг |
|---|---|---|---|
| (a) REST | p95 латентности отправки | 800 ms | `--rest-p95-threshold-ms` |
| (a) REST | доля неуспешных отправок | 5% | `--rest-error-rate-threshold` |
| (b) WS fanout | p95 / p99 end-to-end delivery latency | 2000 / 5000 ms | `--fanout-p95-threshold-ms` / `--fanout-p99-threshold-ms` |
| (c) WS churn | p95 latency connect+subscribe и resume | 1500 ms | `--churn-p95-threshold-ms` |
| (c) WS churn | доля неуспешных subscribe/resume | 5% | `--churn-error-rate-threshold` |

Это **мягкие, ориентировочные** значения — baseline ещё не снят на момент
написания теста, поэтому это не более чем "разумная отправная точка", а не
угаданные заранее цифры. **После первого реального прогона пересмотрите их**
и передавайте явно.

При нарушении любого порога процесс Locust завершается с ненулевым exit
code (`environment.process_exit_code = 1`) — `docker compose run`
транслирует этот код наружу, что делает сценарий пригодным для CI-гейта.

## Baseline-числа (первый прогон)

*Не заполнено — см. предупреждение в начале файла. Впишите сюда вывод
Locust (`Aggregated`-строку из его отчёта: msg/sec = `Requests/s`, p50/p95/p99
из колонок percentiles) после первого реального прогона на docker-compose
стенде, отдельно для каждого сценария и, для (b), отдельно для
`--chat-kind group` и `--chat-kind supergroup`.*

```
(a) REST throughput
  дата/время:
  --users / --spawn-rate / --run-time:
  msg/sec (Requests/s):
  p50 / p95 / p99, ms:
  error rate, % (в т.ч. отдельно доля 429 от rate limiter):

(b) WS fanout latency — group (fanout_on_write)
  --writer-rate / читателей (--users):
  delivery_fanout_on_write p50/p95/p99, ms:
  delivery_ts_field_on_write p50/p95/p99, ms (для сравнения, см. находку про ts):
  на каком количестве открытых соединений/msg-rate начинает расти p95/p99:

(b) WS fanout latency — supergroup (active_subscribers)
  (аналогично)

(c) WS connection churn + resume
  --churn-rate / --users:
  ws_connect_subscribe p50/p95/p99, ms, error rate:
  ws_resume p50/p95/p99, ms, error rate:
  деградирует ли что-то при увеличении --churn-rate (и на каком значении)
```

## Что дальше

- Реально прогнать всё на docker-compose стенде и заполнить раздел выше.
- По цифрам первого прогона пересмотреть значения `--*-threshold-*`.
- Находки из раздела ["Находки"](#находки-изменившие-дизайн-теста) — каждая
  кандидат на отдельный промпт (правка `try_send`/`ts`, IP vs per-user rate
  limit, мёртвый `RATE_LIMITER_ENABLED`).
- Если baseline упрётся в вопрос "а что там на стороне consumer lag / Kafka
  backlog" — это по постановке отдельный, последующий промпт (сопоставление
  с Grafana/kafka-exporter здесь намеренно не делается).
