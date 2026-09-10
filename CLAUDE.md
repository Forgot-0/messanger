# CLAUDE.md

Индекс проекта для AI-ассистентов. Читается автоматически в начале каждой сессии.
Здесь — карта и инварианты. Подробности живут в `README.md` и `api-docs.md`.

## Что это за проект

Backend мессенджера (Telegram-подобного): чаты/группы/каналы, сообщения, вложения,
реакции, read receipts, звонки, push-уведомления, realtime через WebSocket.

Технически — **production-ready модульный монолит на FastAPI**, выросший из
[fastapi_template](https://github.com/Forgot-0/fastapi_template) (README местами всё ещё
называет проект «FastAPI Template» и `social_github` — это исторические названия, репозиторий один).

Ключевые архитектурные решения:

- CQRS-style: команды/запросы через собственный медиатор (`app/core/mediators`).
- DI на [Dishka](https://github.com/reagento/dishka), никаких глобальных синглтонов.
- Доменные события: **transactional outbox → Postgres WAL → Debezium (CDC) → Kafka → FastStream**.
- Realtime: собственный WS-gateway поверх Redis Streams (`app/core/websocket`).

## Карта документации

| Файл | Что там |
|---|---|
| `README.md` (~1500 строк) | Полное описание `app/core` и `app/auth` (эталонный модуль), событийная архитектура, core-сервисы, **раздел «Правила для AI-ассистентов» — обязателен к соблюдению**, пошаговый гайд «Создание нового модуля» |
| `api-docs.md` (~1250 строк) | Контракт HTTP + WebSocket API, полный каталог кодов ошибок, неочевидное поведение, практическая схема для Flutter-клиента |
| `messenger-anatomy.html` | Визуальный разбор «Анатомия мессенджера» (открывать в браузере) |
| `loadtests/README.md` | Нагрузочные сценарии (locust): WS fanout, WS churn, REST throughput |
| `CLAUDE.md` (этот файл) | Индекс: карта, инварианты, команды |

Прикладные модули (`profiles`, `chats`, `notifications`) в README сознательно не описаны —
они повторяют структуру `app/auth`.

## Стек

Python 3.14 (`uuid7` берётся из stdlib `uuid`), FastAPI 0.135+, SQLAlchemy 2.0 async + asyncpg,
PostgreSQL 18 (`wal_level=logical`), Alembic, Dishka, Redis/Valkey, Taskiq (+ taskiq-redis),
Kafka (продюсер — aiokafka, консьюмеры — FastStream), Debezium 2.7, MinIO (S3),
pyvips/ffprobe для медиа, LiveKit (звонки), Firebase Admin (push), aiosmtplib + Jinja2 (почта),
structlog, Prometheus/Grafana/Loki/Vector, pytest + pytest-asyncio + testcontainers,
ruff/mypy/pylint/pre-commit. Пакетный менеджер — Poetry.

## Один код — четыре процесса

| Процесс | Entrypoint | Назначение |
|---|---|---|
| `app` | `app.main:init_app()` (gunicorn + uvicorn worker) | HTTP API и WebSocket-gateway |
| `consumers` | `app.consumers:app` (FastStream, порт 9002) | Консьюмеры Kafka + фоновые коалесеры реакций и read receipts |
| `queue_worker` | `app.tasks:broker` (Taskiq) | Фоновые задачи (почта, обработка медиа, push) |
| `scheduler` | `app.tasks:scheduler` (Taskiq) | Периодические задачи, в т.ч. очистка outbox |
| `migrations` | one-shot | `alembic upgrade head` + `python -m app.init_data` |

Инфраструктура в compose: `db`, `redis`, `kafka`, `minio`, `debezium`, `debezium_connector`.

## Слои и поток запроса

```
HTTP route (app/<module>/routes/v1/*.py)
  → mediator.handle_command(XxxCommand) / handle_query(XxxQuery)
    → XxxCommandHandler / XxxQueryHandler (app/<module>/commands|queries/...)
      → Repository (app/<module>/repositories/*.py)
        → Model (app/<module>/models/*.py)
```

Команды **меняют** состояние, запросы **только читают**. Побочные эффекты в query-хендлерах запрещены.
Регистрация команд/запросов и провайдеров — в `app/<module>/providers.py`, сборка контейнера — `app/core/di/container.py`.

## Карта модулей

- `app/core` — инфраструктура: `api/` (builder, rate_limiter, schemas, filter_mapper),
  `commands.py`/`queries.py` (базовые классы), `configs/`, `consumers/` (DTO событий + `EventIdempotencyGuard`),
  `db/` (base_model, repository, session), `di/`, `events/`, `outbox/`, `filters/`, `log/`, `mediators/`,
  `message_brokers/` (Kafka), `middlewares/`, `services/` (auth/JWT/RBAC, mail, media, queues, storage, idempotency),
  `websocket/` (manager, presence, keys), `metrics.py`, `models.py`, `routers.py` (`/health`), `tasks.py`.
- `app/auth` — **эталонный модуль**. Пользователи, сессии, JWT, Argon2, OAuth (Google/Yandex/GitHub), RBAC.
- `app/profiles` — профили пользователей, аватары, контакты.
- `app/chats` — самый крупный модуль: чаты, участники, сообщения, вложения, реакции, read receipts, звонки, WS.
- `app/notifications` — устройства, уведомления, offline-push через Firebase.

## Модуль chats: что нужно знать

- **Типы чатов** (`ChatType`): `direct`, `group`, `supergroup`, `channel`.
- **Стратегии фанаута** (`ChatFanoutStrategy`): `fanout_on_write`, `active_subscribers`, `channel_subscribers`.
  Порог переключения — `FAN_OUT_WRITE_THRESHOLD = 500` в `app/chats/config.py`.
- **WS-протокол**: субпротокол `chat.v1`, вход `GET /api/v1/chats/ws/`, токен через query/заголовок.
  Клиентские операции (`WSClientOp`): `ping`, `pong`, `subscribe`, `unsubscribe`, `resume`.
  Серверные события (`WSEventType`) — в `app/chats/schemas/ws.py`.
  Переподключение: `resume` с `last_seq` на чат (режим `last_seq_per_chat`).
- **Доставка**: `ChatDeliveryRouter` (`app/chats/services/delivery_router.py`) читает топик `chats`
  и раскладывает события по Redis Streams конкретных gateway-процессов; для оффлайн-получателей
  шлёт сигнал в топик `chats.offline-delivery`, откуда `notifications` делает push.
- **Коалесеры**: реакции и read receipts не рассылаются по одной — они склеиваются в окне
  (`REACTIONS_COALESCE_WINDOW_MS`, `READ_RECEIPTS_COALESCE_WINDOW_MS`, по 500 мс) фоновыми задачами
  в процессе `consumers` (`app/chats/tasks/coalescer.py`, `app/chats/tasks/read_coalescer.py`).
- **Вложения**: двухшаговая загрузка через presigned PUT в MinIO
  (`chat-pending-attachments` → валидация/обработка → `chat-attachments`). Лимиты MIME и размеров — в `config.py`.
- **Звонки**: LiveKit, выдача room-токена (`ROOM_TOKEN_TTL`, `ROOM_MAX_PARTICIPANTS`).
- Ключи Redis — только через `app/chats/keys.py` и `app/core/websocket/keys.py`, не собирать строки руками.

## Событийная модель

Имя события задаётся в `__event_name__` на dataclass-событии рядом с моделью, формат `<module>.<entity>.<action>`.
**Топик Kafka = префикс до первой точки**: `auth.user.created` → топик `auth`, `chats.message.sent` → топик `chats`.
Это делает `OutboxMessage.create()` в `app/core/outbox/model.py`, а роутит Debezium через `EventRouter`
(`transforms.outbox.route.by.field: topic`, конфиг — `infra/debezium/outbox-connector.json`).

Существующие события:

| Событие | Модуль |
|---|---|
| `auth.user.created`, `auth.user.verified`, `auth.session.created`, `auth.session.suspicious` | auth |
| `profiles.profile.created`, `profiles.profile.updated` | profiles |
| `chats.chat.created`, `chats.chat.updated`, `chats.chat.deleted` | chats |
| `chats.member.added`, `chats.member.kicked`, `chats.member.banned`, `chats.member.left` | chats |
| `chats.message.sent`, `chats.message.readed`, `chats.message.modified`, `chats.message.deleted` | chats |
| `chats.message.reaction_updated` | chats |

Дополнительный топик без outbox: `chats.offline-delivery` (сигнал на push, публикуется delivery-router'ом).

## Таблицы БД

`users`, `user_permissions`, `user_roles`, `roles`, `permissions`, `role_permissions`, `sessions`, `oauth_accounts`,
`profiles`, `contacts`,
`chats`, `chat_members`, `chat_member_bans`, `chat_roles`, `chat_user_profiles`, `messages`, `message_attachments`,
`message_reactions`, `message_reaction_counters`, `read_receipts`,
`notifications`, `user_device_tokens`,
`outbox_messages`.

## Инварианты, которые легко нарушить

1. **Trailing slash обязателен.** `redirect_slashes=False` в `app/main.py` — `/api/v1/chats` вернёт 404, нужно `/api/v1/chats/`.
2. **Новая ORM-модель регистрируется в `app/core/models.py`**, иначе Alembic её не увидит.
3. **Доменные события — только через outbox.** `event_bus.publish(model.pull_events())` вызывается
   **до** `session.commit()`, в той же транзакции. Прямой `broker.send_event(...)` для доменных событий запрещён.
4. **Каждый FastStream-подписчик идемпотентен** через `EventIdempotencyGuard` (Redis, ключ `consumers:processed:{group}:{event_id}`, TTL 7 дней).
   Доставка at-least-once, дубликаты — норма.
5. **Топики и `group_id` — в `config.py` модуля**, не в коде подписчика и не в `.env`-хардкоде.
6. **Фильтрация и пагинация — через `app.core.filters`** (`XxxFilter(BaseFilter)` + `find_by_filter`), не ручной `WHERE`/`LIMIT`.
7. **Проверка прав — через RBAC-менеджер** первой строкой хендлера или FastAPI-зависимостью. Никаких `if user.role == ...` в бизнес-логике.
8. **Postgres должен стартовать с `wal_level = logical`** (`infra/postgres/postgresql.conf`), иначе Debezium не создаст слот
   и события просто накопятся в `outbox_messages`.
9. **Сеть `app-network` — external**, её нужно создать до `docker compose up`.
10. **`.env` обязателен.** В `ENVIRONMENT=production` `AppConfig` падает, если пусто хоть одно из
    `SECRET_KEY`, `JWT_SECRET_KEY`, `POSTGRES_*`, `REDIS_HOST`, `BROKER_URL`.
11. **OpenAPI/Swagger отдаётся только в `local`/`testing`** — в проде `openapi_url=None`.
12. **Python 3.14** (`requires-python = ">=3.14,<3.15"`); используется `uuid7` из stdlib и синтаксис дженериков PEP 695.

## Команды

Локальный запуск всего стека:

```bash
docker network create app-network && docker compose up --build
```

Прод-конфигурация:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml -f docker-compose.monitoring.yml up -d --build
```

Тесты (нужен работающий Docker — testcontainers поднимает Postgres, Redis, MinIO):

```bash
cp .env.test .env && poetry run pytest tests -q
```

Маркеры расставляются автоматически по пути: `tests/**/unit` → `unit`, `**/integration` → `integration`, `**/e2e` → `e2e`.

Линтеры и типы:

```bash
poetry run ruff check . && poetry run mypy . && poetry run pylint app
```

Миграции:

```bash
poetry run alembic revision --autogenerate -m "описание" && poetry run alembic upgrade head
```

## Эндпоинты и порты

- API: `http://localhost:8000`, префикс `/api/v1`
- Swagger: `/docs`, OpenAPI: `/api/v1/openapi.json` (только local/testing)
- Health: `GET /health`, метрики: `GET /metrics` (у `consumers` — на порту 9002)
- Kafka Connect REST: `http://localhost:8083` (статус CDC: `/connectors/outbox-connector/status`)
- MinIO Console: `http://localhost:9001`

## Деплой

`.github/workflows/ci-cd.yml`: на push в `main` — `ruff check ./app`, затем `pytest`, затем job `deploy`,
который по SSH заходит на прод, делает `git pull --ff-only` и запускает `infra/deploy.sh`
(down → up -d --build → prune). Нужны секреты репозитория `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`,
опционально `DEPLOY_PATH` (по умолчанию `/home/forgot/messanger`). `.env` на сервере лежит вне git и правится руками.

## Правила работы в этом репозитории

- **Не коммитить и не пушить.** Изменения оставляем в рабочем дереве, коммит делает владелец репозитория.
- Соблюдать раздел «Правила для AI-ассистентов» в `README.md` — он приоритетнее любых догадок.
- Новый модуль строится копированием структуры `app/auth`, а не изобретением своей.
- Каждое изменение бизнес-логики сопровождается тестом в `tests/` по аналогии с `tests/auth`.
- Новые зависимости не добавлять, если задача решается существующими сервисами
  (`CacheRepository`, `QueueService`, `StorageService`, `BaseMailService`, `BaseMessageBroker`, `IdempotencyStore`).
- Секреты и настройки — только через `.env` / `BaseConfig`, никаких хардкодов ключей, хостов, топиков и `group_id`.
