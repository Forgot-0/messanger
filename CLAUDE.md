# CLAUDE.md

Индекс проекта для AI-ассистентов. Читается автоматически в начале каждой сессии.
Здесь — карта и инварианты. Подробности живут в `README.md` и `api-docs.md`.

## Что это за проект

Backend мессенджера (Telegram-подобного): чаты/группы/каналы, сообщения, вложения,
реакции, read receipts, звонки, push-уведомления, realtime через WebSocket.

Технически — **production-ready модульный монолит на FastAPI**, выросший из
[fastapi_template](https://github.com/Forgot-0/fastapi_template) (README местами всё ещё
называет проект «FastAPI Template»).

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
Kafka (продюсер — aiokafka, консьюмеры — FastStream), Debezium 2.7, SeaweedFS (S3, клиент — aioboto3),
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

Инфраструктура в compose: `db`, `redis`, `kafka`, `seaweedfs`, `debezium`, `debezium_connector`.

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
  `message_brokers/` (Kafka), `middlewares/`, `services/` (auth/JWT/RBAC, mail, media, queues, storage, idempotency;
  в `storage/` активна реализация `aioboto/` на aioboto3, `aminio/` оставлена как legacy и в DI не подключена),
  `websocket/` (manager, presence, keys), `metrics.py`, `models.py`, `routers.py` (`/health`), `tasks.py`.
- `app/auth` — **эталонный модуль**. Пользователи, сессии, JWT, Argon2, OAuth (Google/Yandex/GitHub), RBAC.
  Смена username — `PUT /users/me/username/` (`ChangeUsernameCommand`, правила — `User.validate_username`,
  конфиг `USERNAME_*`), проверка имени — `GET /users/username/check/`. Источник правды для username — `users`.
- `app/profiles` — профили пользователей, аватары (бакет приватный, presign — `services/avatar_urls.py`),
  история фото (`profile_photos`, `profiles.photo_id` — текущее; `services/photo_storage.py`, варианты под
  `{user_id}/{photo_id}/`, до `MAX_PROFILE_PHOTOS = 100`; `GET /profiles/{id}/photos/`, `DELETE /profiles/avatar/`,
  `PUT|DELETE /profiles/photos/{photo_id}/...`), `profiles.username` — **проекция** auth (консьюмер
  `consumers/user.py` по `auth.user.username_changed`, та же группа, что у `auth.user.verified`),
  ссылки на внешние профили (`profile_links`),
  адресная книга: контакты, блок-лист, слепые идентификаторы (`/contacts`),
  настройки приватности (`profile_privacy`, `services/privacy.py`, `/profiles/privacy/`).
  Профиль и идентификатор заводит консьюмер `app/profiles/consumers/user.py` по `auth.user.verified`.
- `app/chats` — самый крупный модуль: чаты, участники, сообщения, вложения, реакции, read receipts, звонки, WS.
- `app/notifications` — устройства, уведомления, offline-push через Firebase.

## Модуль chats: что нужно знать

- **Типы чатов** (`ChatType`): `direct`, `group`, `supergroup`, `channel`.
- **Стратегии фанаута** (`ChatFanoutStrategy`): `fanout_on_write`, `active_subscribers`, `channel_subscribers`.
  Порог переключения — `FAN_OUT_WRITE_THRESHOLD = 500` в `app/chats/config.py`.
- **WS-протокол**: субпротокол `chat.v1`, вход `GET /api/v1/chats/ws/`, токен через query/заголовок.
  Клиентские операции (`WSClientOp`): `ping`, `pong`, `subscribe`, `unsubscribe`, `resume`, `typing`.
  Серверные события (`WSEventType`) — в `app/chats/schemas/ws.py`.
  Переподключение: `resume` с `last_seq` на чат (режим `last_seq_per_chat`).
- **Доставка**: `ChatDeliveryRouter` (`app/chats/services/delivery_router.py`) читает топик `chats`
  и раскладывает события по Redis Streams конкретных gateway-процессов; для оффлайн-получателей
  шлёт сигнал в топик `chats.offline-delivery`, откуда `notifications` делает push.
- **Коалесеры**: реакции и read receipts не рассылаются по одной — они склеиваются в окне
  (`REACTIONS_COALESCE_WINDOW_MS`, `READ_RECEIPTS_COALESCE_WINDOW_MS`, по 500 мс) фоновыми задачами
  в процессе `consumers` (`app/chats/tasks/coalescer.py`, `app/chats/tasks/read_coalescer.py`).
- **«Печатает…»** (`op: "typing"`, `TypingAction`) — эфемерное, **не доменное** событие: мимо outbox,
  Kafka и БД. `TypingCommandHandler` (`app/chats/commands/websockets/typing.py`) в процессе `app`
  сам раскладывает `typing_start`/`typing_stop` по стримам gateway через
  `ChatDeliveryRouter.route_ephemeral` (та же стратегия фан-аута, без offline-сигнала, без автора).
  Троттлинг и кэш прав — в памяти соединения (`WSConnection.typing_by_chat`, `services/typing.py`):
  одинаковый `action` не чаще `TYPING_BROADCAST_INTERVAL_MS`, проверка членства/прав/блока —
  раз в `TYPING_CONTEXT_TTL_SECONDS`, так что поток кадров клавиатуры не доходит ни до Redis, ни до
  Postgres. У записи стрима есть `DeliveryDTO.expires_at`: gateway выбрасывает просроченные
  (важно для `xautoclaim`), счётчик `chat_ws_gateway_stream_expired_total`. Ошибки — `ws.error`,
  исключение не рвёт сокет.
- **Пакетная пересылка** `POST /chats/{chat_id}/messages/forward_many/` (`ForwardMessagesCommand`):
  до `MAX_FORWARD_MESSAGES = 100`, одна транзакция, `seq` выделяются одним
  `allocate_message_seq(count=N)`, порядок — по `seq` источника. Альбом = одно сообщение со многими
  вложениями, копируется целиком (`Message.create_forward`, вложения по `id`, с `width/height/duration`;
  `relationship(order_by=MessageAttachment.id)`). `hide_author` — копия без `forwarded_from_*`.
  `SendedMessageEvent.notify` (по умолчанию `True`) — `False` у всех сообщений пакета, кроме
  последнего: delivery-router не шлёт по ним offline-сигнал, push один на пакет.
- **Кто прочитал** `GET .../messages/{message_id}/reads/`: только автор, только group/supergroup
  с `member_count <= READ_MARKS_MAX_MEMBERS = 100` (`Chat.tracks_read_marks`), только 7 дней.
  Источник — `read_receipt_marks` (PK `chat_id, user_id, seq`): `ReadReceiptFlusher` пишет строку на
  каждое реальное продвижение курсора в таких чатах (флаг `marks` едет в payload коалесера). Время
  для сообщения — первая отметка с `seq >= S` (LATERAL с `LIMIT 1` по участникам). Чистит
  taskiq-задача `chats.read_marks.cleanup` по BRIN-индексу `read_at`.
- **Закреплённые сообщения** — таблица `chat_pinned_messages` (PK `chat_id, message_id`,
  индекс `chat_id, message_seq`), до `MAX_PINNED_MESSAGES = 100`, право `message:pin`.
  `PinMessageCommand` берёт строку чата `FOR UPDATE` (лимит без гонок, `seq` всё равно выделяется
  тем же UPDATE), создаёт системное сообщение `type=system, action=message_pinned,
  reply_to_id=<закреплённое>` (`Message.create_system`, колонка `messages.action`). События
  `chats.message.pinned` / `chats.message.unpinned` (WS `message_pinned` / `message_unpinned`).
  Удаление сообщения открепляет его в той же транзакции. Роутер — `routes/v1/pins.py`,
  префикс `/chats/{chat_id}/pinned_messages`.
- **Персональное состояние чата** живёт в колонках `chat_members`: `pinned_at`, `archived_at`,
  `notifications_muted_until`, `draft`, `draft_updated_at`. Меняется только своё membership —
  `PATCH /api/v1/chats/{chat_id}/state/` (user_id из JWT, RBAC не нужен, нет членства = 404).
  Лимит пинов — `MAX_PINNED_CHATS = 5`, порядок пинов — `pinned_at DESC` (поля `pin_order` нет),
  под него есть partial-индекс `ix_chat_members_user_pinned`. В `GET /chats/` пины исключены из
  keyset-тела и приклеиваются отдельным запросом к первой странице; `archived` — отдельный набор.
  `notifications_muted_until` **не** `muted_until`: первый — личный мьют push, второй — модераторский.
- **Кто в чате для списка**: `GET /chats/` отдаёт `ChatDTO.peer` (только direct) и
  `members_preview` (только group/supergroup, лимит `CHAT_MEMBERS_PREVIEW_LIMIT = 3`).
  Оба набираются одним `ChatRepository.get_chat_counterparts` на всю страницу — LATERAL с
  `LIMIT` внутрь `chat_members`, а не оконная функция: `row_number() OVER (PARTITION BY chat_id)`
  читает партицию целиком и на супергруппе в 1 млн участников стоит 153 мс против 0.2 мс.
  Профили собеседников подмешиваются в тот же список, что идёт в `MessageService.image_urls`, —
  второго прохода по presign быть не должно.
- **Поиск по сообщениям**: `GET /api/v1/chats/messages/search/` — статический путь в
  `routes/v1/chats.py`, объявлен **выше** `/{chat_id}/`. Postgres FTS по `messages.content`,
  конфигурация `simple` (смешанные языки, стемминг вреден), последний терм префиксный,
  tsquery собирается вручную в `app/chats/services/search_query.py`. GIN-индекс
  `ix_messages_content_fts_simple` создаётся миграцией `d4f2a91c60b7` вручную и исключён из
  сравнения в `migrations/env.py` (alembic expression-индексы не сравнивает и выписал бы им DROP).
  Скоуп видимости — join на `chat_members` вызывающего; по `joined_at` намеренно не режем.
- **Модерация участников**: бан/разбан (`PATCH|DELETE /members/{id}/ban/`), модераторский мьют
  (`PATCH|DELETE /members/{id}/mute/`, право `member:mute`, событие `chats.member.muted`).
  `muted_until` (модератор) ≠ `notifications_muted_until` (личный мьют push).
- **Владелец = `chats.created_by`**, не «исторический создатель». `POST /chats/{id}/transfer_ownership/`
  переписывает `created_by`, новому владельцу даёт роль owner, прежнему — admin (строка чата под
  `FOR UPDATE`). `Chat.leave()` запрещает выход именно по `created_by`.
- **Публичное имя чата** (`chats.username`, только у публичных group/supergroup/channel):
  уникальность без учёта регистра даёт `uq_chats_username_lower` (`lower(username) text_pattern_ops`,
  он же обслуживает префиксный поиск). Поиск публичных чатов `GET /chats/search/` — BitmapOr этого
  индекса и GIN `ix_chats_public_name_fts_simple` (`to_tsvector('simple', coalesce(name,''))`,
  partial `is_public AND deleted_at IS NULL`). Оба индекса — expression, созданы миграцией
  `77ee1cfd425a` вручную и исключены в `migrations/env.py`. В запросе конфиг FTS — литерал
  `'simple'::regconfig`, а не bind-параметр, иначе выражение не совпадёт с индексом.
- **Инвайт-ссылки** (`chat_invite_links`): использование списывается условным `UPDATE ... RETURNING`
  (`ChatInviteLinkRepository.consume`), без `SELECT FOR UPDATE`. Превью/вступление —
  статические `/chats/invites/{code}/`, объявлены выше `/{chat_id}/`. Флаг
  `creates_join_request` делает ссылку «по заявке» (с `usage_limit` несовместим).
- **Заявки на вступление** — таблица `chat_join_requests` (PK `chat_id, user_id`), роутер
  `routes/v1/join_requests.py` (префикс `/chats/{chat_id}/join_requests`, право `member:invite`;
  `DELETE /me/` — отзыв своей заявки). Вход в режим: ссылка
  с `creates_join_request` или `chats.join_by_request` (публичный `POST /chats/{id}/join/`).
  Оба пути вступления отвечают `JoinChatResultDTO` (`joined` | `requested`), общая часть —
  `ChatJoinRequestService.submit`. «Ожидает решения» = `resolved_at IS NULL` (под partial-индекс
  `ix_chat_join_requests_pending`), `status` держит тип решения; строка переживает решение, на ней
  кулдаун повторной заявки `JOIN_REQUEST_RETRY_AFTER_SECONDS`.
  Решения **только пакетные**: `POST /approve/` и `POST /decline/` с `user_ids` (до
  `MAX_JOIN_REQUESTS_BULK = 100`, лимит живёт в схеме запроса, как у `forward_many`) и
  `DELETE /` — «отклонить все» одним `UPDATE ... WHERE resolved_at IS NULL` (по partial-индексу,
  `synchronize_session="fetch"` оставлен сознательно — на Postgres это тот же запрос
  с `RETURNING` ключей, зато заявки в сессии не остаются `PENDING`). Строки пакета берутся `FOR UPDATE`
  по возрастанию `user_id` (детерминированный порядок блокировок), всё, что решать нечего,
  уходит в `skipped`, а не в ошибку. Одобрение добавляет участников, двигает `member_count`
  одним шагом на размер пакета и засчитывает ссылкам `usage_count` одним
  `ChatInviteLinkRepository.credit_usage` (без условий `consume`: вступление состоялось).
  События заявок агрегированные — одно на пакет (`ApprovedChatJoinRequestsEvent` /
  `DeclinedChatJoinRequestsEvent` с `user_ids`, у «отклонить все» — `all: true` и `count`
  без списка, как у `UnpinnedMessagesEvent`); регистрирует их `Chat`, а не строка заявки.
  `chats.member.added` при этом по-прежнему на каждого участника. События
  `chats.join_request.created/approved/declined/cancelled` не идут в общий фан-аут:
  `ChatDeliveryRouter._route_join_request` кладёт их только тем, у кого в чате есть право
  `member:invite`, и — для решения — заявителю. Адресаты считаются
  `ChatRepository.user_ids_with_permission`: роли резолвятся по самому праву (`chat_roles`,
  шесть строк), затем `role_id IN (...)` ложится в `ix_chat_members_chat_role_user` вместе
  с `chat_id`. **Сортировки в этом запросе быть не должно** — с `ORDER BY user_id`
  планировщик берёт `ix_chat_members_chat_active_user` ради порядка и фильтрует весь чат
  (300k участников: 53 мс против 0.2 мс). Персональный `permissions_overrides` учитывается
  только как запрет. Push по заявкам нет.
- **Аватар группы/канала**: слот загрузки — в Redis (`ChatAvatarKeys`), не в БД; обработка —
  taskiq-задача `chats.avatar.process` (`ChatAvatarService`: pyvips в `to_thread`, чтение pending
  пиннится `stat`). Варианты лежат в публичном бакете `chat-avatars` под `{chat_id}/{upload_token}/`,
  `chats.avatars` хранит URL'ы, `avatar_s3_key` — URL 64px jpg. Старая версия удаляется после замены.
- **Блокировки в чатах** читаются только из проекции `chat_user_blocks` через `ChatPrivacyService`
  (`app/chats/services/privacy.py`); модуль чатов не ходит в `blocked_users`. Проекцию наполняет
  консьюмер `app/chats/consumers/blocks.py` (группа `chat_block_projection`) по
  `profiles.user.blocked/unblocked`. Личка — `USER_BLOCKED` в обе стороны; добавить в группу того,
  кто тебя заблокировал, — `USER_PRIVACY_RESTRICTED`; фото и онлайн блокирующего скрываются
  от заблокированного в REST-ответах (`hide_avatars` — до `image_urls`).
- **Вложения**: двухшаговая загрузка через presigned PUT в SeaweedFS
  (`chat-pending-attachments` → валидация/обработка → `chat-attachments`). Лимиты MIME и размеров — в `config.py`.
- **Медиаконвейер** (`services/attachment_processor.py` → `AttachmentMediaProcessor`, зовётся из
  `ProccessAttachmentsCommandHandler`): файл качается из pending один раз (пиннится `stat`), дальше по типу.
  Модель как в Telegram/WhatsApp: тяжёлое (сжатие фото и видео, HEIC → JPEG) делает клиент, сервер чистит
  метаданные и строит превью. Фото: JPEG без EXIF-поворота чистится **без перекодирования**
  (`app/core/services/media/jpeg.py` вырезает APP1/APP13/COM и хвост после EOI, ICC и Adobe остаются; чистый
  JPEG от клиента выходит байт в байт); JPEG с поворотом, PNG и WebP перекодируются pyvips'ом
  (`services/attachment_images.py`); GIF — как есть; HEIC/HEIF в `ALLOWED_IMAGE_MIMES` нет. Видео — ремукс без
  метаданных (`-map_metadata -1`, `+faststart`), первый кадр — постер (HDR тонмапится); **HLS и серверного
  перекодирования видео нет**: играется оригинал, перемотка — Range по presigned-ссылке. Фото и постеры дают
  `previews` (WebP 320/800/1280, JSONB) и `thumbhash` (`app/core/services/media/thumbhash.py`, чистый Python).
  ffmpeg — порт `MediaTranscoder` (`extract_frame`, `strip_metadata`; реализация `transcode/ffmpeg.py`,
  провайдится в `ChatModuleProvider`). Производные лежат в том же приватном бакете под
  `media/{chat_id}/{attachment_id}/…` (`AttachmentStorageKeys`), не под `chats/…`: SeaweedFS хранит S3 на
  filer'е, файл и одноимённый каталог не уживутся.
- **Общие медиа** `GET /chats/{chat_id}/media/?type=photo|video|media|file|voice|link`: `message_seq`
  денормализован в `message_attachments` (ставит `Message.create`), индекс
  `ix_msg_attachments_shared_media`; по запросу на тип и слияние в Python (не `IN (...)` — иначе сортировка
  всей истории). `link` — флаг `messages.has_links` (регулярка как у линкифаера клиента) и
  `ix_messages_chat_links`.
- **Звонки**: LiveKit, выдача room-токена (`ROOM_TOKEN_TTL`, `ROOM_MAX_PARTICIPANTS`).
- Ключи Redis — только через `app/chats/keys.py` и `app/core/websocket/keys.py`, не собирать строки руками.

## Событийная модель

Имя события задаётся в `__event_name__` на dataclass-событии рядом с моделью, формат `<module>.<entity>.<action>`.
**Топик Kafka = префикс до первой точки**: `auth.user.created` → топик `auth`, `chats.message.sent` → топик `chats`.
Разбирает имя `EventName.parse()` (`app/core/events/naming.py`), раскладывает по колонкам
`MediatorEventBus` (`app/core/events/mediator/service.py`), а роутит Debezium через `EventRouter`
(`transforms.outbox.route.by.field: topic`, конфиг — `infra/debezium/outbox-connector.json`).
`outbox_messages.aggregate_type` — **агрегат** (`user`, `chat`, `message`), как в каноническом
outbox-паттерне, а не копия модуля; модуль живёт в `topic`.

Существующие события:

| Событие | Модуль |
|---|---|
| `auth.user.created`, `auth.user.verified`, `auth.user.deleted`, `auth.user.username_changed` | auth |
| `auth.session.created`, `auth.session.suspicious` | auth |
| `profiles.profile.created`, `profiles.profile.updated` | profiles |
| `profiles.contact.added`, `profiles.contact.removed` | profiles |
| `profiles.user.blocked`, `profiles.user.unblocked` | profiles |
| `profiles.privacy.updated` | profiles |
| `chats.chat.created`, `chats.chat.updated`, `chats.chat.deleted`, `chats.chat.ownership_transferred` | chats |
| `chats.member.added`, `chats.member.kicked`, `chats.member.banned`, `chats.member.muted`, `chats.member.left` | chats |
| `chats.message.sent`, `chats.message.readed`, `chats.message.modified`, `chats.message.deleted` | chats |
| `chats.message.pinned`, `chats.message.unpinned` | chats |
| `chats.message.reaction_updated` | chats |
| `chats.join_request.created`, `chats.join_request.approved`, `chats.join_request.declined`, `chats.join_request.cancelled` | chats |

Дополнительный топик без outbox: `chats.offline-delivery` (сигнал на push, публикуется delivery-router'ом).
`chats.typing.started` / `chats.typing.stopped` — только имена в WS-конверте: эти кадры не проходят
ни через outbox, ни через Kafka (см. «Печатает…» выше).

## Таблицы БД

`users`, `user_permissions`, `user_roles`, `roles`, `permissions`, `role_permissions`, `sessions`, `oauth_accounts`,
`profiles` (+ `photo_id`), `profile_photos`, `profile_links`, `user_contacts`, `user_identifiers`, `pending_contacts`, `blocked_users`,
`profile_privacy`, `profile_privacy_exceptions`,
`chats` (+ `username`, `avatars`), `chat_members` (+ per-user состояние: `pinned_at`, `archived_at`, `notifications_muted_until`,
`draft`, `draft_updated_at`), `chat_member_bans`, `chat_roles`, `chat_user_profiles` (+ копия настроек приватности `privacy_*`),
`chat_user_blocks` (проекция `blocked_users`), `chat_user_contacts` (проекция `user_contacts`),
`chat_user_privacy_exceptions` (проекция `profile_privacy_exceptions`),
`chat_invite_links` (+ `creates_join_request`), `chat_join_requests`, `chat_pinned_messages`,
`messages` (+ `action` у системных, `has_links`),
`message_attachments` (+ `message_seq`, `previews`, `thumbhash`), `message_reactions`, `message_reaction_counters`, `read_receipts`, `read_receipt_marks`,
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
13. **Статические пути объявляются до параметризованных.** `/contacts/blocked/`, объявленный после
    `/contacts/{user_id}/`, уедет в параметризованный роут и вернёт 422.
14. **Идентификаторы адресной книги хранятся только как HMAC** (`user_identifiers`, `pending_contacts`).
    Pepper — `CONTACT_IDENTIFIER_PEPPER` в `.env`, в проде пустым быть не может. Ротации нет:
    сырые email/телефоны нигде не лежат, смена pepper обесценивает обе таблицы.
15. **Чужие события топика отсеиваются ветвлением по `event_name` внутри подписчика** (`DictEventDTO`
    плюс `model_validate` payload'а). Фильтр `@subscriber(filter=...)` требует ещё и пустой ветки
    по умолчанию, иначе FastStream пишет `SubscriberNotFound` уровня ERROR на каждое чужое сообщение.
16. **Всё, что читается из pending-бакета после `get_stat`, пиннится этим же `stat`.**
    Presigned PUT живёт весь свой TTL и допускает повторную запись, поэтому между валидацией
    и промоушеном объект можно подменить. `download_range`/`download_to_path`/`download_bytes`
    принимают `stat=`, `copy_object` — `source_stat=`; они переводятся в `IfMatch`/`CopySourceIfMatch`
    (SeaweedFS их соблюдает — см. тесты в `tests/chats/integration/commands/attachments/test_proccess.py`).
    Без пиннинга проверки размера и magic-bytes относятся к байтам, которых в бакете уже нет.
17. **Хранилище — только через `StorageService`.** Активная реализация — `AioBotoStorageService`
    (`app/core/services/storage/aioboto/`), собирается в `CoreProvider` как APP-scope async-генератор:
    два aiobotocore-клиента (внутренний и публичный) живут столько же, сколько контейнер.
    Публичный доступ к бакету даёт bucket policy, которую `ensure_buckets()` применяет на старте,
    а не identity в конфиге SeaweedFS. Подпись — SigV4, адресация — path-style.
18. **Бакеты аватаров профиля приватные.** `profiles` и `pending-avatar` — `Policy.NONE`.
    В `profiles.avatars`, `profile_photos.avatars` и в проекции `chat_user_profiles.avatar_s3_key`
    лежат **только ключи объектов** (`{user_id}/{photo_id}/{size}.{fmt}`), URL туда не пишутся и
    ветки «если это http» в коде нет; ссылки подписываются на чтении —
    `ProfileAvatarUrlService.attach()` (модуль `profiles`, кэш подписей в Redis по ключу объекта,
    TTL `AVATAR_URL_TTL = 300`) и `MessageService.image_urls()` (модуль `chats`). Новый ответ,
    отдающий `avatars` или `avatar_s3_key`, обязан пройти через них, иначе клиент получит ключ
    вместо ссылки. Публичным остался только `chat-avatars` (аватары групп и каналов): там
    `avatar_s3_key` — готовый URL, presign не нужен.
19. **Приватность решается в одном порядке: блок → персональное исключение → видимость.**
    Оси (`PrivacyRule`), значения (`PrivacyVisibility`) и само решение — в `app/core/privacy.py`
    (`is_allowed`), чтобы profiles и chats считали одинаково. «Контакт» — это тот, кого владелец
    настройки держит в **своей** адресной книге, поэтому аноним (публичный
    `GET /profiles/u/{username}/`) контактом не бывает никогда. Строки `profile_privacy` может
    не быть — это значит «всё открыто» (`DEFAULT_VISIBILITY`), поэтому читать настройки только
    через `ProfilePrivacyService` / `ChatPrivacyService`, а не `JOIN`'ом в обход. Модуль чатов
    ходит исключительно в свои проекции (`chat_user_profiles.privacy_*`, `chat_user_contacts`,
    `chat_user_privacy_exceptions`), наполняемые консьюмерами по `profiles.privacy.updated` и
    `profiles.contact.added/removed`; в `profile_privacy` и `user_contacts` он не заглядывает.
    Любой новый ответ с фото, онлайном или новым действием в личке обязан пройти через эти
    сервисы — иначе настройка просто не сработает.
20. **Предикат запроса должен буквально совпадать с предикатом partial-индекса.** Postgres не выводит
    `is_deleted = false` из `is_deleted IS false` (так рендерится `.is_(False)`) и уходит в seq scan.
    Для partial-индексов писать `~Model.flag` / `Model.flag` (см. `get_link_messages_page`), а значения
    в предикате — литералами, не bind-параметрами (`text("status = 'PENDING'")`). Проверять EXPLAIN'ом.
21. **Username уникален без учёта регистра — это держит `uq_users_username_lower`** (уникальный
    индекс по `lower(username)` в `users`). `UserRepository.is_username_taken()` — только быстрый
    ответ до записи: параллельный запрос может его обогнать, поэтому команда, которая создаёт или
    меняет username, ловит `IntegrityError` на commit и отдаёт `DUPLICATE_USER` / `USERNAME_TAKEN`
    (так сделаны регистрация и смена имени). `profiles.username` и `chat_user_profiles.username` —
    проекции без уникальности: при переименовании имя ненадолго бывает у двоих.

## Команды

Локальный запуск всего стека:

```bash
docker network create app-network && docker compose up --build
```

Прод-конфигурация:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml -f docker-compose.monitoring.yml up -d --build
```

Тесты (нужен работающий Docker — testcontainers поднимает Postgres, Redis, SeaweedFS):

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
- SeaweedFS: S3 API `http://localhost:8333`, master UI `http://localhost:9333`, filer `http://localhost:8888`
- Консоль SeaweedFS (аналог MinIO Console: бакеты, браузер объектов, состояние кластера) —
  сервис `seaweedfs_admin`, `http://127.0.0.1:23646`, логин/пароль из `SEAWEEDFS_ADMIN_USER` /
  `SEAWEEDFS_ADMIN_PASSWORD`. Наружу не публикуется, на прод ходить через
  `ssh -L 23646:localhost:23646 <user>@<host>`.

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
