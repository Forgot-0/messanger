# API Documentation — social_github

> Сверено с исходным кодом на `main` (2026-08-14). Основной референс для написания клиента (роуты, Pydantic-схемы, DTO, exception-классы, конфиги).

Типы даны в псевдо-TypeScript (`interface`, `X | null`, `"a" | "b"` для enum) — однозначно транслируется в Dart-модели. Все пути — от `API_V1_STR = /api/v1`, кроме `/health` и `/metrics`, у которых префикса нет. Раздел 0 — чек-лист неочевидного поведения, стоит прочитать первым.

---

## Оглавление

- [0. КРИТИЧНО: неочевидное поведение API](#0-критично-неочевидное-поведение-api)
- [1. Общие конвенции API](#1-общие-конвенции-api)
- [2. Ошибки: формат и полный каталог кодов](#2-ошибки-формат-и-полный-каталог-кодов)
- [3. Аутентификация и пользователи (`/auth`, `/users`, `/roles`, `/permissions`, `/sessions`)](#3-аутентификация-и-пользователи)
- [4. Профили (`/profiles`)](#4-профили-profiles)
- [5. Чаты — REST (`/chats`)](#5-чаты--rest)
- [6. Чаты — WebSocket (`/chats/ws/`)](#6-чаты--websocket)
- [7. Уведомления (`/devices`, `/notifications`)](#7-уведомления)
- [8. Сводка ролей и прав (chat + system)](#8-сводка-ролей-и-прав)
- [9. Гайд по реализации на Flutter](#9-гайд-по-реализации-на-flutter)

---

## 0. КРИТИЧНО: неочевидное поведение API

Это самое важное в документе. Если ИИ-агент прочитает только этот раздел, он всё равно избежит большинства багов.

| # | Что нужно знать |
|---|---|
| 1 | **Слэш в конце пути обязателен.** `redirect_slashes=False` в FastAPI-приложении (`app/main.py`). **Абсолютно все** пути требуют слэш в конце (`/auth/login/`, `/chats/`, `/profiles/{id}/`...). Запрос без слэша → `404 Not Found`, редиректа не будет. |
| 2 | **Формат ошибки — вложенный конверт**: `{ "error": { "code", "message", "detail" }, "status": number, "request_id": "uuid", "timestamp": number }`. См. раздел 2. |
| 3 | **Пагинация списков.** Обычный `PageResult<T>` (профили, проекты, позиции, заявки, роли, права, сессии, пользователи, уведомления) отдаёт только 4 поля: `items, total, page, page_size`. `has_next`/`total_pages` — Python `@property`, они не сериализуются и их нужно считать на клиенте: `total_pages = ceil(total / page_size)`, `has_next = page < total_pages`. Исключение — чат-эндпоинты со своей курсорной пагинацией (`ListChats`, `MessagesDTO`, `ListMembers`), у них `has_next` — реальное поле. |
| 4 | **`POST /auth/login/`** использует `OAuth2PasswordRequestForm` → тело запроса **`application/x-www-form-urlencoded`**, поля называются `username` и `password` (не `email`!). JSON туда слать нельзя, FastAPI вернёт 422. |
| 5 | **Refresh-токен** никогда не приходит и не уходит в JSON. Сервер кладёт его в **HttpOnly-cookie** `refresh_token` (`Secure=true`, `SameSite=strict`, `Path=/`). `POST /auth/refresh/` читает его из cookie автоматически. Подробности и последствия для мобильного/веб-клиента — в разделе 9. |
| 6 | **Время жизни access-токена** — `ACCESS_TOKEN_EXPIRE_MINUTES = 5`. Клиенту обязателен агрессивный proactive-refresh или retry-on-401 механизм. Refresh-токен живёт 60 дней. |
| 8 | **`POST /profiles/` не существует.** Профиль создаётся автоматически бэкендом через Kafka-consumer сразу после `POST /users/register/` (слушает топик `users`). Между регистрацией и появлением профиля возможна небольшая задержка (eventual consistency) — `GET /profiles/{id}/` может на короткое время вернуть 404 сразу после регистрации. |
| 9 | **Аватар профиля**: `avatars: { "32"\|"64"\|"256"\|"512": { "jpg": url, "webp": url, "avif": url } }` — 4 размера × 3 формата на размер. См. раздел 4.5. |
| 10 | **Загрузка аватара — presigned PUT**, тем же механизмом, что и вложения чата (раздел 6.5), но валидация типа/размера файла происходит **асинхронно**, уже после подтверждения загрузки — `POST /profiles/avatar/upload_complete/` всегда отвечает `200 OK`, даже если файл в итоге окажется невалидным и аватар не обновится. См. раздел 4.5. |
| 11 | Раздела "realtime" (`/chats/realtime/presence/`, `/chats/realtime/ws/status/`) в коде нет. Presence отдаётся через `GET /chats/{chat_id}/members/?include_presence=true` и через WS. |
| 12 | **WebSocket-протокол** — полноценный протокол с 4 командами клиента (`subscribe`, `unsubscribe`, `resume`, `ping`/`pong`) и ~13 типами server-push событий (`new_message`, `message_edited`, `message_deleted`, `messages_read`, `member_joined`, `member_left`, `member_kick`, `member_banned`, `chat_created`, `chat_updated`, `attachment_success`, `chat_deleted`, `reaction_update`, плюс служебные `ws.ready/subscribed/unsubscribed/history/pong/ping/error`). В `payload` каждого доменного события лежит дельта `event` (поля конкретного типа: `reader_id`, `target_user_id`, `deleted_by`, ...) и `event_id` для дедупликации — доставка at-least-once. Полный `MessageDTO` приходит только в `new_message`/`message_edited`. Полностью расписан в разделе 7. |
| 13 | **Роли проекта** — реальные сид-роли: `owner(id=1)`, `maintainer(id=2)`, `developer(id=4, id=3 не существует)`, `user(id=5)`, с непустой картой прав. См. раздел 8. |
| 14 | **429 Too Many Requests** не проходит через `ApplicationError` — это обычный FastAPI `HTTPException`, отдаётся как `{"detail": "Too Many Requests"}`, без `error/status/request_id/timestamp`. Обрабатывать нужно отдельной веткой по HTTP-статусу 429. |
| 15 | **`GET /users/me/`** возвращает облегчённый `UserResponse`: только `{id, username, email}`. Роли/права/сессии — через `GET /users/` (админский, постранично) или `GET /users/sessions/`. |
| 16 | **`GET /users/sessions/`** возвращает голый массив `SessionDTO[]`, не обёрнутый в `PageResult`. |
| 17 | **`PATCH /notifications/read_all/`** возвращает голое число (int) — количество обновлённых уведомлений, не объект. |

---

## 1. Общие конвенции API

### 1.1 Базовый URL

```
{BASE_URL}/api/v1/...
```

`API_V1_STR = "/api/v1"`. Единственное исключение — служебные эндпоинты без версионирования и без префикса:

- `GET /health` — healthcheck, всегда возвращает `200 "Ok"`.
- `GET /metrics` — Prometheus-метрики (не нужен фронтенду).

### 1.2 Заголовок авторизации

```
Authorization: Bearer <access_token>
```

Передаётся на все `🔒`-эндпоинты. Access-токен получается через `/auth/login/`, `/auth/refresh/` или OAuth callback.

### 1.3 Content-Type

По умолчанию везде `application/json`, кроме:
- `POST /auth/login/` — `application/x-www-form-urlencoded` (см. п. 0.4).
- `PUT <presigned upload URL>` (S3/MinIO, аватар и вложения чата) — тело запроса, сырые байты файла.

### 1.4 Успешный ответ

Тело ответа — это **сам DTO напрямую**, без обёртки `{data: ...}` или `{success: true, ...}`. Например `GET /profiles/1/` возвращает прямо `{"id": 1, "avatars": {...}, ...}`, а не `{"data": {...}}`.

### 1.5 Пагинация (offset/page-based) — `PageResult<T>`

Используется в большинстве списковых эндпоинтов (профили, роли/права/сессии auth, уведомления):

```ts
interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  // ВНИМАНИЕ: total_pages / has_next / has_previous / next_page / previous_page
  // в реальном JSON-ответе ОТСУТСТВУЮТ (это @property в Python-dataclass,
  // FastAPI их не сериализует). Считать на клиенте:
  //   total_pages = (total / page_size).ceil()
  //   has_next    = page < total_pages
  //   has_previous = page > 1
}
```

Query-параметры запроса, общие почти для всех списков: `page: int = 1` (`ge=1`), `page_size: int = 20` (`ge=1, le=100`), `sort: string | null` (см. 1.7).

### 1.6 Курсорная пагинация (только в чатах)

`GET /chats/`, `GET /chats/{id}/messages/`, `GET /chats/{id}/members/` используют собственные DTO с курсором, а не `PageResult`. У них `has_next` — **реальное** поле. Подробности в разделе 6.

### 1.7 Сортировка

Единый формат для всех `sort`-параметров: строка вида `"field1:asc,field2:desc"`. Пример: `sort=created_at:desc,username:asc`. Направление — `asc` или `desc`.

### 1.8 UUID и числовые ID

- `user_id`, `notification_id`, `role_id` (система/чат/проект), `permission.id`, `session.id` — целые числа (`int`, некоторые `bigint`).
- `chat_id`, `message_id`, `attachment_id`, `position_id`, `application_id`, `upload_token` — UUID-строки.

### 1.9 Даты

Все datetime-поля — ISO 8601 строки в UTC (стандартная Pydantic-сериализация `datetime`). Поле `date_birthday` — просто `YYYY-MM-DD` (тип `date`).


## 2. Ошибки: формат и полный каталог кодов

### 2.1 Формат ошибки

Все ошибки уровня приложения (`ApplicationError` и наследники) возвращаются в едином конверте:

```ts
interface ErrorResponse {
  error: {
    code: string;       // например "NOT_FOUND_USER"
    message: string;    // человекочитаемое сообщение (обычно на английском)
    detail: Record<string, unknown> | Array<Record<string, unknown>> | null;
  };
  status: number;        // дублирует HTTP-статус
  request_id: string;    // UUID запроса, также приходит в заголовке X-Request-ID
  timestamp: number;     // unix-time (float, секунды)
}
```

Пример реального ответа `404 NOT_FOUND_USER`:

```json
{
  "error": {
    "code": "NOT_FOUND_USER",
    "message": "User not found",
    "detail": { "user_by": "123", "user_field": "id" }
  },
  "status": 404,
  "request_id": "5b1f9b0a-6e21-4b2a-8a9d-3c9a2e7a9f10",
  "timestamp": 1752835200.123
}
```

**Код на Flutter должен читать поля как `response['error']['code']`, а НЕ `response['code']`.**

### 2.2 Особые случаи, которые НЕ следуют формату из 2.1

| Случай | HTTP статус | Реальное тело ответа |
|---|---|---|
| Ошибка валидации запроса (Pydantic не смог распарсить body/query/path — опечатка в поле, не то число и т.п.) | 422 | `{ "error": { "code": "VALIDATION", "message": "Validation exception", "detail": [ { "loc": ["body","field"], "msg": "...", "type": "..." } ] } , "status": 422, "request_id": "...", "timestamp": ... }`. Код именно `"VALIDATION"` (не `"VALIDATION_EXCEPTION"`), и `detail` — **массив**, а не объект, как у всех остальных ошибок. |
| Превышен rate limit | 429 | `{ "detail": "Too Many Requests" }` — **никакого** `error/status/request_id/timestamp`. Это чистый FastAPI `HTTPException`, обработчик `ApplicationError` его не перехватывает. |
| Непойманное исключение сервера (баг) | 500 | `{ "error": { "code": "UNKNOWN_EXCEPTION", "message": "Unknown exception", "detail": null }, "status": 500, ... }` |

Рекомендация для Flutter-слоя обработки ошибок: сначала проверять HTTP-статус на 429 отдельной веткой, затем пытаться распарсить `body['error']['code']`, с fallback на `body['detail']` (429/сырые FastAPI-ошибки) и общий "неизвестная ошибка" на случай сетевого сбоя без тела.

### 2.3 Коды по модулю `core` / auth-инфраструктура

| code | HTTP | detail | Когда возникает |
|---|---|---|---|
| `NOT_AUTHENTICATED` | 401 | `{}` | Запрос на `🔒`-эндпоинт без заголовка `Authorization` вообще |
| `INVALID_TOKEN` | 403 | `{}` | Токен есть, но невалиден (плохая подпись, не тот формат) |
| `EXPIRED_TOKEN` | 400 | `{}` | Access-токен истёк (обычно каждые 5 минут — самый частый кейс, триггер для refresh) |
| `ACCESS_DENIED` | 403 | `{ "permissions": string[] }` | Не хватает системных прав (RBAC) либо аккаунт неактивен (`is_active=false`, тогда `permissions: []`) |
| `VALIDATION` | 422 | `[{loc, msg, type}]` | Некорректное тело/query/path запроса (см. 2.2) |
| `UNKNOWN_EXCEPTION` | 500 | `null` | Непредвиденная ошибка сервера |

### 2.4 Коды модуля `auth` (`/auth`, `/users`, `/roles`, `/permissions`, `/sessions`)

| code | HTTP | detail |
|---|---|---|
| `WRONG_LOGIN_DATA` | 400 | `{ "username": string }` |
| `NOT_FOUND_USER` | 404 | `{ "user_by": string\|number, "user_field": string }` |
| `DUPLICATE_USER` | 409 | `{ "field": string, "value": string }` — при регистрации, если email/username занят |
| `PASSWORD_MISMATCH` | 400 | `{}` — `password` и `password_repeat` не совпали |
| `NOT_FOUND_ROLE` | 404 | `{ "name": string }` |
| `DUPLICATE_ROLE` | 409 | `{ "name": string }` |
| `INVALID_ROLE_NAME` | 400 | `{ "name": string }` |
| `NOT_FOUND_PERMISSIONS` | 404 | `{ "permissions": string[] }` |
| `DUPLICATE_PERMISSION` | 409 | `{ "name": string }` |
| `PROTECTED_PERMISSION` | 409 | `{ "permission": string }` — попытка изменить системную защищённую permission |
| `NOT_FOUND_OR_INACTIVE_SESSION` | 400 | `{}` — refresh-токен не найден/сессия неактивна |
| `OAUTH_STATE_NOT_FOUND` | 404 | `{ "state": string }` |
| `LINKED_ANOTHER_USER_OAUTH` | 409 | `{ "provider": string }` |
| `NOT_EXIST_PROVIDER_OAUTH` | 400 | `{ "provider": string }` — провайдер не `google`/`yandex`/`github` |
| `EMAIL_NOT_CONFIRMED` | 403 | `{ "email": string }` |
| `TOKEN_IN_BLACKLIST` | 409 | `{}` |

### 2.5 Коды модуля `profiles`

| code | HTTP | detail |
|---|---|---|
| `NOT_FOUND_PROFILE` | 404 | `{ "profile_id": number }` |
| `ALREADY_EXIST_PROFILE` | 409 | `{}` |
| `TOO_LONG_SKILL_NAME` | 400 | `{ "skill_name": string }` — лимит 30 симв. |
| `TOO_LONG_DISPLAY_NAME` | 400 | `{ "display_name": string }` — лимит 100 симв. |
| `TOO_LONG_BIO` | 400 | `{ "bio": string }` — лимит 1024 симв. |
| `AVATAR_NOT_TYPE_IMAGE` | 400 | `{ "type": string }` — реальный MIME-тип загруженного файла (определяется через `python-magic` по содержимому, а не по расширению) не начинается с `image/` |
| `AVATAR_SIZE` | 400 | `{ "current_size": number }` — файл больше `AVATAR_MAX_SIZE` (5 МБ) |

⚠️ Оба кода выше возникают **асинхронно**, внутри фоновой задачи обработки аватара — они не приходят как HTTP-ответ ни на `/avatar/presign/`, ни на `/avatar/upload_complete/` (оба всегда отвечают `200`, если запрос сам по себе корректен). См. раздел 4.5.

### 2.6 Коды модуля `chats`

| code | HTTP | detail |
|---|---|---|
| `NOT_FOUND_CHAT` | 404 | `{ "chat_id": string }` |
| `INVALID_CHAT_ROLE` | 422 | `{ "role_id": number }` |
| `NOT_CHAT_MEMBER` | 403 | `{ "chat_id": string, "user_id": number }` |
| `NOT_FOUND_MESSAGE` | 404 | `{ "message_id": string }` |
| `CHAT_ACCESS_DENIED` | 403 | `{ "chat_id": string, "requester_id": number }` — не хватает прав по роли в чате |
| `SLOW_MODE_OUT_OF_RANGE` | 400 | `{ "seconds": number, "valid_range": [0, 86400] }` |
| `SLOW_MODE_LIMIT` | 429 | `{ "chat_id": string, "retry_after": number }` — слишком часто пишет при включённом slow-mode |
| `ALREADY_CHAT_MEMBER` | 409 | `{ "user_id": number, "chat_id": string }` |
| `TOO_LONG_CHAT_ROLE_NAME` | 400 | `{ "role_name": string, "max_len": 32 }` |
| `DIRECT_CHAT_EXISTS` | 409 | `{ "chat_id": string }` |
| `MEMBER_LIMIT_EXCEEDED` | 400 | `{ "limit": number }` — лимит зависит от типа чата (2/500/1000000/10000000), см. раздел 9 |
| `MESSAGE_TOO_LONG` | 400 | `{ "length": number, "max_length": 4096 }` |
| `LIVEKIT_ERROR` | 502 | `{ "reason": string }` |
| `LIVEKIT_UNAUTHORIZED` | 502 | `{}` |
| `NO_ACTIVE_CALL` | 404 | `{ "chat_id": string }` |
| `ACTIVE_CALL_EXISTS` | 409 | `{ "chat_id": string }` |
| `ATTACHMENT_VALIDATION` | 400 | `{ "mime_type": string }` — недопустимый MIME или превышен размер |
| `INVALID_UPLOAD_TOKEN` | 400 | `{ "token": string }` |
| `ATTACHMENT_LIMIT_EXCEEDED` | 400 | `{ "count": number }` — макс. 10 медиа или 1 файл на сообщение |
| `ATTACHMENT_NOT_FOUND` | 404 | `{ "attachment_id": string }` |
| `IDEMPOTENCY_CONFLICT` | 409 | `{ "key": string }` — повторный запрос с тем же `Idempotency-Key` ещё обрабатывается |
| `INVALID_MESSAGE` | 400 | `{ "reason": string }` |
| `EMPTY_ATTACHMENT_UPLOAD_REQUEST` | 400 | `{}` |
| `MAX_LIMIT_CURSOR` | 429 | `{ "max": number, "current": number }` — только в WS-команде `resume`, лимит 20 курсоров |
| `INVALID_REACTION` | 400 | `{ "emoji": string }` — эмодзи не входит в каталог реакций; см. 6.7.4 |
| `REACTION_NOT_ALLOWED` | 400 | `{ "emoji": string, "allowed": string[] }` — режим чата `some`, эмодзи не в белом списке; см. 6.7.4 |
| `REACTIONS_DISABLED` | 403 | `{ "chat_id": string }` — в чате `reactions_mode = "none"`; см. 6.7.4 |
| `TOO_MANY_REACTIONS` | 400 | `{ "limit": number, "scope": "user" \| "message" }` — превышен лимит реакций; см. 6.7.4 |

⚠️ `ATTACHMENT_MEDIA_VALIDATION` (класс `AttachmentMediaValidationError`) в этой таблице **намеренно не указан** — он никогда не долетает до HTTP-ответа: возникает только внутри фонового воркера `ProccessAttachmentsCommandHandler` (см. 6.5), там же перехватывается и сворачивается в `attachment_status: "error"`. Клиенту как код ошибки API не отдаётся.

### 2.7 Коды модуля `notifications`

| code | HTTP | detail |
|---|---|---|
| `NOT_FOUND_NOTIFICATION` | 404 | `{ "notification_id": number }` |
| `NOTIFICATION_ACCESS_DENIED` | 403 | `{ "notification_id": number }` |


## 3. Аутентификация и пользователи

Базовые пути: `/auth/*`, `/users/*`, `/roles/*`, `/permissions/*`, `/sessions/*` (все под `/api/v1`).

### 3.1 Модель токенов

- **Access-токен** (JWT): передаётся в заголовке `Authorization: Bearer <token>`, живёт **5 минут** (`ACCESS_TOKEN_EXPIRE_MINUTES=5`). Возвращается в теле JSON-ответа как `access_token`.
- **Refresh-токен**: живёт **60 дней** (`REFRESH_TOKEN_EXPIRE_DAYS=60`). Никогда не появляется в JSON. Сервер сам кладёт/удаляет его в HttpOnly-cookie `refresh_token` при `login/refresh/oauth-callback` (`set_refresh_token`) и `logout` (`delete_refresh_token`). Параметры cookie: `Path=/`, `HttpOnly=true`, `Secure=true`, `SameSite=strict`. Важные следствия — раздел 9.2.
- Один и тот же access-токен не инвалидируется при логауте (JWT stateless) — инвалидируется именно refresh-сессия.

### 3.2 `POST /users/register/`

Регистрация. Публичный эндпоинт.

**Request** (JSON, `UserCreateRequest`):
```ts
{
  username: string;   // 4–100 симв., паттерн ^[a-zA-Z0-9 ,.'-]+$
  email: string;       // валидный email
  password: string;    // 8–128 симв., должен содержать: заглавную, строчную, цифру, спецсимвол из набора !@#$%^&*(),.?":{}|<>
  password_repeat: string;
}
```
Если `password` не проходит проверку сложности → `422 VALIDATION` (ошибка на уровне Pydantic, ещё до бизнес-логики). Если `password !== password_repeat` → `400 PASSWORD_MISMATCH` (проверяется в обработчике команды, а не в схеме).

**Response `201`** (`UserResponse` — **не** полный `UserDTO**):
```ts
{ id: number; username: string; email: string }
```

**Ошибки:** `400 PASSWORD_MISMATCH`, `409 DUPLICATE_USER` (`detail: {field: "username"|"email", value}`).

После успешной регистрации бэкенд асинхронно (через Kafka) создаёт профиль пользователя — см. раздел 4.1. Пользователь создаётся сразу с `is_active=true`, `is_verified=false`, ролью `user`.

### 3.3 `POST /auth/login/` ⚠️ form-urlencoded, не JSON

**Request:** `Content-Type: application/x-www-form-urlencoded`, тело — стандартная OAuth2-форма:
```
username=<строка>&password=<строка>
```
Поле называется именно `username`, даже если по факту сервер, вероятно, ищет пользователя и по email тоже (это одно текстовое поле логина). `grant_type`/`scope`/`client_id`/`client_secret` можно не передавать.

Rate limit: 4 запроса / 5 минут (по IP+маршруту).

**Response `200`** (`AccessTokenResponse`):
```ts
{ access_token: string }
```
Плюс `Set-Cookie: refresh_token=...` в заголовках ответа.

**Ошибки:** `400 WRONG_LOGIN_DATA` (`detail: {username}`).

### 3.4 `POST /auth/refresh/`

Без тела запроса. Refresh-токен читается автоматически из cookie `refresh_token` (её нужно просто передавать вместе с запросом — во Flutter это означает cookie-aware HTTP-клиент, см. раздел 9.2).

Rate limit: 4 запроса / 5 минут.

**Response `200`**: `AccessTokenResponse` (то же самое, `{access_token}}`), плюс обновлённая `Set-Cookie: refresh_token=...` (ротация refresh-токена при каждом обновлении).

**Ошибки:** `400 INVALID_TOKEN` / `400 EXPIRED_TOKEN`, `404 NOT_FOUND_OR_INACTIVE_SESSION`.

### 3.5 `POST /auth/logout/`

Без тела запроса (тоже читает `refresh_token` из cookie). **Response `204`**. Удаляет cookie на клиенте (`Set-Cookie` с истёкшим временем) и деактивирует сессию на сервере.

**Ошибки:** `400 INVALID_TOKEN`.

### 3.6 Подтверждение email

1. **`POST /auth/verifications/email/`** — запросить код. Rate limit: 3/час.
   Request: `{ email: string }`. Response `204`. Ошибки: `404 NOT_FOUND_USER`.
2. **`POST /auth/verifications/email/verify/`** — подтвердить. Rate limit: 3/час.
   Request: `{ token: string }`. Response `204`. Ошибки: `400 INVALID_TOKEN`, `404 NOT_FOUND_USER`.
   Токен приходит пользователю на email (ссылка/код, шаблон письма вне зоны ответственности фронтенда) и живёт `EMAIL_RESET_TOKEN_EXPIRE_MINUTES = 15` минут.

### 3.7 Сброс пароля

1. **`POST /auth/password-resets/`** — запросить код сброса. Rate limit: 3/час.
   Request: `{ email: string }`. Response `204`. Ошибки: `404 NOT_FOUND_USER`.
2. **`POST /auth/password-resets/confirm/`** — подтвердить новый пароль. Rate limit: 3/час.
   Request (`ResetPasswordRequest`, наследует `PasswordMixinSchema`):
   ```ts
   { token: string; password: string; password_repeat: string }
   ```
   Те же правила сложности пароля, что и при регистрации. Response `204`. Ошибки: `400 INVALID_TOKEN` / `400 PASSWORD_MISMATCH`, `404 NOT_FOUND_USER`.

### 3.8 OAuth (Google / Yandex / GitHub)

`{provider}` ∈ `google | yandex | github`. Неверный провайдер → `400 NOT_EXIST_PROVIDER_OAUTH`.

1. **`GET /auth/oauth/{provider}/authorize/`** 🔓 — получить URL для редиректа на страницу авторизации провайдера (обычный вход/регистрация через OAuth). Rate limit: 4/5мин.
   Response `200`: `{ url: string }`. Открыть этот `url` в системном браузере/WebView.
2. **`GET /auth/oauth/{provider}/authorize/connect/`** 🔒 — привязать OAuth-провайдера к уже залогиненному аккаунту. Требует `Authorization`. Rate limit: 4/5мин.
   Response `200`: `{ url: string }`.
3. **`GET /auth/oauth/{provider}/callback/?code=...&state=...`** 🔓 — callback от провайдера (обычно провайдер сам делает редирект браузера сюда; фронтенду нужно перехватить редирект / deep link и переслать `code`+`state`, либо это должно открываться прямо в системном браузере, а моб. приложение ловит финальный deep-link с результатом — конкретная схема зависит от того, как настроен `redirect_uri` у провайдера в конфиге бэкенда, уточнить у бэкенд-команды).
   Response `200`: `AccessTokenResponse` + `Set-Cookie: refresh_token`.
   Ошибки: `400 NOT_EXIST_PROVIDER_OAUTH`, `404 OAUTH_STATE_NOT_FOUND` / `NOT_FOUND_USER`, `409 LINKED_ANOTHER_USER_OAUTH`.

### 3.9 `GET /users/me/` ⚠️ облегчённый ответ

**Response `200`** (`UserResponse`, НЕ полный `UserDTO`):
```ts
{ id: number; username: string; email: string }
```
Для ролей/прав нужен отдельный запрос (нет прямого self-эндпоинта для этого — доступно только админам через `GET /users/` с фильтром по id, либо через `GET /users/sessions/` для сессий).

Внутренняя проверка: аккаунт должен быть `is_active=true` (по умолчанию `true` сразу при регистрации, в текущей кодовой базе флаг деактивации не выставляется автоматически нигде — то есть на практике эта проверка почти всегда проходит).

**Ошибки:** `400 INVALID_TOKEN`, `403 ACCESS_DENIED`, `404 NOT_FOUND_USER`.

### 3.10 Управление ролями/правами пользователя (админ)

| Эндпоинт | Требуемые системные права (**все** сразу, AND) | Request | Response |
|---|---|---|---|
| `POST /users/{user_id}/roles/` | `role:assign` | `{ role_name: string }` | `200`, тело пустое |
| `DELETE /users/{user_id}/roles/{role_name}/` | `user:update` **и** `role:remove` | — | `204` |
| `POST /users/{user_id}/permissions/` | `permission:update` **и** `user:update` | `{ permissions: string[] }` | `200`, тело пустое |
| `DELETE /users/{user_id}/permissions/` | `permission:update` **и** `user:update` | `{ permissions: string[] }` | `204` |

Проверка прав — это `user_permissions ⊇ required_permissions` (пользователь должен иметь **все** перечисленные права; роли `super_admin`/`system_admin` проходят любую проверку автоматически). Ошибки: `403 ACCESS_DENIED` (`detail.permissions` = недостающие права), `404 NOT_FOUND_ROLE` / `NOT_FOUND_PERMISSIONS` / `NOT_FOUND_USER`.

### 3.11 `GET /users/` (список пользователей, админ)

Требует `user:view`.

Query (`GetUsersRequest`): `id?, username?, email?, is_active?: bool, is_verified?: bool, role_name?, page=1, page_size=20, sort?`.

**Response `200`**: `PageResult<UserDTO>` — здесь уже **полный** объект:
```ts
interface UserDTO {
  id: number;
  username: string;
  email: string;
  roles: RoleDTO[];
  permissions: PermissionDTO[];
  sessions: SessionDTO[];
  is_active: boolean;
  is_verified: boolean;
}
interface RoleDTO { id: number; name: string; description: string; security_level: number; permissions: PermissionDTO[] }
interface PermissionDTO { id: number; name: string }
```

### 3.12 `GET /users/sessions/` ⚠️ голый массив

Свои сессии текущего пользователя. **Response `200`: `SessionDTO[]`** — именно массив, БЕЗ обёртки `{items:[...]}`/`PageResult`.
```ts
interface SessionDTO {
  id: number;
  user_id: number;
  device_info: string;
  user_agent: string;
  last_activity: string; // ISO datetime
  is_active: boolean;
}
```

### 3.13 Роли (`/roles/`) — системный RBAC, админ-функциональность

| Метод | Путь | Права | Request | Response |
|---|---|---|---|---|
| GET | `/roles/` | `role:view` | Query: `GetRolesRequest {name?, page, page_size, sort}` | `PageResult<RoleDTO>` |
| POST | `/roles/` | `role:create` | `RoleCreateRequest {name: string, description: string, security_level: number, permissions: string[]}` | `201`, пусто |
| POST | `/roles/{role_name}/permissions/` | `role:create` | `RolePermissionRequest {permission: string[]}` ⚠️ поле называется `permission` (без "s"), не `permissions` | `200`, пусто |
| DELETE | `/roles/{role_name}/permissions/` | `role:update` | `RolePermissionRequest {permission: string[]}` | `200`, пусто |

Ошибки: `400 INVALID_ROLE_NAME`, `403 ACCESS_DENIED`, `404 NOT_FOUND_ROLE`/`NOT_FOUND_PERMISSIONS`, `409 DUPLICATE_ROLE`/`PROTECTED_PERMISSION`.

Нет отдельного `PATCH`/`DELETE .../{role_id}/` для роли целиком — управление правами роли только точечное (`POST`/`DELETE .../permissions/`).

### 3.14 Права (`/permissions/`)

| Метод | Путь | Права | Request | Response |
|---|---|---|---|---|
| GET | `/permissions/` | `permission:view` | Query: `GetPermissionsRequest {name?, page, page_size, sort}` | `PageResult<PermissionDTO>` |
| POST | `/permissions/` | `permission:create` | `PermissionCreateRequest {name: string}` | `201`, пусто |
| DELETE | `/permissions/{name}/` | `permission:create` ⚠️ (не `permission:delete`!) | — | `204` |

Ошибки: `403 ACCESS_DENIED`, `404 NOT_FOUND_PERMISSIONS`, `409 PROTECTED_PERMISSION`.

### 3.15 Сессии — админский обзор (`/sessions/`)

Отличается от `GET /users/sessions/` (там — только свои): здесь можно смотреть/завершать сессии по фильтру.

| Метод | Путь | Права | Query/Request | Response |
|---|---|---|---|---|
| GET | `/sessions/` | `user:view` | `GetSessionsRequest {user_id?, is_active?, page, page_size, sort}` | `PageResult<SessionDTO>` |
| DELETE | `/sessions/{session_id}/` | `user:update` | — | `204` |

Ошибки: `403 ACCESS_DENIED`, `404 NOT_FOUND_OR_INACTIVE_SESSION`.

### 3.16 Сид-данные системных ролей (справочно)

| id (по имени) | Роль | `security_level` | Права |
|---|---|---|---|
| — | `super_admin` | 10 | ВСЕ права системы |
| — | `system_admin` | 9 | `system:manage_settings`, `system:view_logs`, `user:create/update/delete/view`, `role:view/assign/remove` |
| — | `user` | 1 | нет прав — роль по умолчанию для новых регистраций |

Полный список системных строк-прав: `system:manage_settings`, `system:view_logs`, `user:create`, `user:update`, `user:delete`, `user:view`, `user:impersonate`, `role:create`, `role:update`, `role:delete`, `role:view`, `role:assign`, `role:remove`, `permission:create`, `permission:update`, `permission:delete`, `permission:view`.


## 4. Профили (`/profiles`)

### 4.1 Важно: профиль создаётся автоматически

Эндпоинта `POST /profiles/` **не существует**. `profile.id` всегда равен `user.id` (связь 1:1). Как только `POST /users/register/` отработал, бэкенд асинхронно (Kafka-consumer, топик `users`) сам создаёт профиль. Между регистрацией и появлением профиля возможна короткая задержка — если сразу после регистрации запросить `GET /profiles/{id}/`, теоретически можно словить `404 NOT_FOUND_PROFILE`; на практике стоит либо повторить запрос через секунду, либо просто не делать этот запрос сразу после регистрации.

### 4.2 `GET /profiles/` 🔓 (публичный)

Query (`GetProfilesRequest`): `username?, display_name?, skills?: string[], page=1, page_size=20 (≤100), sort?`.

**Response `200`**: `PageResult<ProfileDTO>` (только 4 поля пагинации, см. 1.5).

### 4.3 `GET /profiles/{profile_id}/` 🔓 (публичный)

**Response `200`**: `ProfileDTO`. Ошибки: `404 NOT_FOUND_PROFILE`.

```ts
interface ProfileDTO {
  id: number;                                   // === user_id
  avatars: Record<"32"|"64"|"256"|"512", Record<"jpg"|"webp"|"avif", string>>;
  specialization: string | null;
  display_name: string | null;
  bio: string | null;
  date_birthday: string | null;                 // "YYYY-MM-DD"
  skills: string[];                              // хранятся в lowercase, приходят как обычный массив (Python set → JSON array)
  contacts: ContactDTO[];
}
interface ContactDTO { profile_id: number; provider: string; contact: string }
```

Если у пользователя ещё нет аватара, `avatars` — пустой объект `{}`.

### 4.4 `PUT /profiles/{profile_id}/` 🔒 ⚠️ именно PUT, не PATCH

Разрешено редактировать свой профиль (`profile_id == текущий user_id`) без ограничений, либо чужой — только если у вызывающего есть системные права `profile:update` **и** `user:update` одновременно.

**Request** (`ProfileUpdateRequest`, все поля необязательны, `null`/отсутствие = не менять... **однако** обработчик применяет их напрямую, включая `null`, так что на практике стоит слать полный набор актуальных значений при каждом апдейте, а не только изменённое поле):
```ts
{
  specialization?: string | null;
  display_name?: string | null;   // валидная длина ≤ 99 символов (при 100 и более — ошибка TOO_LONG_DISPLAY_NAME)
  bio?: string | null;             // ≤ 1023 символов
  skills?: string[] | null;        // каждый элемент ≤ 30 символов (TOO_LONG_SKILL_NAME), будет приведён к lowercase
  date_birthday?: string | null;   // "YYYY-MM-DD"
}
```

**Response `200`**: пустое тело. Ошибки: `400 TOO_LONG_*`, `403 ACCESS_DENIED`, `404 NOT_FOUND_PROFILE`.

### 4.5 Загрузка аватара — presigned PUT (тот же механизм, что и вложения чата, см. раздел 6.5)

Двухшаговый флоу, всегда только для **своего** профиля (`profile_id` в пути не передаётся, привязка идёт по JWT).

**Шаг 1 — `POST /profiles/avatar/presign/`** 🔒 (лимит 4/5мин)
```ts
// Request (AvatarPreSignUrlRequest)
{ filename: string }
```
Имя файла санитизируется той же регуляркой `[^\w.\-]` → `_`, ключ в S3 — `{user_id}/{clean_filename}`, бакет `pending_avatar`. Никакой проверки типа/размера на этом шаге нет — сервер просто генерирует ключ и подписывает URL.
```ts
// Response 200 (AvatarPresign)
{
  url: string;       // presigned PUT URL, живёт 90 секунд — короче, чем у вложений чата (3600 сек)!
  file_key: string;  // понадобится на шаге 3
}
```

**Шаг 2 — `PUT <url>`** напрямую в S3/MinIO, минуя бэкенд. Тело — сырые байты файла целиком, без multipart и без дополнительных полей. Успеть уложиться нужно в 90 секунд от шага 1.

**Шаг 3 — `POST /profiles/avatar/upload_complete/`** 🔒 (лимит 4/5мин)
```ts
// Request (AvatarUploadCompleteRequest)
{ file_key: string }   // тот же file_key из шага 1
```
Ответ `200`, тело `"OK"` (строка). Эндпоинт только ставит фоновую задачу в очередь и сразу отвечает — никакой валидации файла на этом шаге не происходит.

**Фоновая обработка** (без обратной связи в API): задача скачивает файл из `pending_avatar`, определяет реальный MIME-тип по содержимому (`python-magic`, не по расширению/заголовку), проверяет размер (≤ 5 МБ, `AVATAR_MAX_SIZE`) — при нарушении генерируется `AVATAR_SIZE`/`AVATAR_NOT_TYPE_IMAGE`, но это не долетает до клиента как HTTP-ответ (см. раздел 2.5), просто новый аватар не появится. При успехе генерируются 4 размера (32/64/256/512) × 3 формата (jpg/webp/avif), заливаются в бакет `profiles` и складываются в `ProfileDTO.avatars`. Клиенту стоит после шага 3 подождать и переопросить `GET /profiles/{id}/` (например с retry/poll в течение нескольких секунд), а если `avatars` не изменился — считать, что загрузка не удалась, и позволить попробовать снова.

### 4.6 Контакты профиля

- **`POST /profiles/{profile_id}/contacts/`** 🔒 — `{ provider: string; contact: string }` → `200`, пусто.
- **`DELETE /profiles/{profile_id}/{provide_contact}/delete/`** 🔒 ⚠️ необычный путь (без `/contacts/` сегмента, с `/delete/` суффиксом) — `provide_contact` в пути — это значение `provider`. → `200`, пусто.

Оба требуют владения профилем либо прав `profile:update` + `user:update`.

## 5. Чаты — REST

Базовый путь для всех эндпоинтов ниже (если не указано иное) — `/chats` и вложенные `/chats/{chat_id}/...`. Все требуют авторизации.

> ⚠️ **Раздел полностью пересобран в версии 2.1** по коду на коммите `7162e9b`. Главные добавления относительно версии 2.0: реакции (5.7), голосовые сообщения и видео-кружки (5.5), поле `profile` в DTO сообщений и участников, `last_message` в `ChatDTO`. (Ссылка на расширенную версию с построчными ссылками на код, ранее заявленную как `docs/chats-module.md`, убрана — такого файла в репозитории нет.)

### 5.0 Карта путей модуля (из `app/chats/routers.py`)

| Префикс | Файл роутера | Тег | Подключён? |
|---|---|---|---|
| `/chats` | `routes/v1/chats.py` | `chats` | ✅ |
| `/chats/{chat_id}/members` | `routes/v1/members.py` | `chat-members` | ✅ |
| `/chats/{chat_id}/messages` | `routes/v1/messages.py` | `chat-messages` | ✅ |
| `/chats/{chat_id}` | `routes/v1/attachments.py` | `chat-attachments` | ✅ |
| `/chats/{chat_id}/calls` | `routes/v1/calls.py` | `chat-calls` | ✅ |
| `/chats` (ws) | `routes/v1/ws.py` | `chats-ws` | ✅ |
| `/chats/{chat_id}/messages/{message_id}/reactions` | `routes/v1/reactions.py` | `chat-reactions` | ✅ |

### 5.1 Типы чатов и роли — коротко

`ChatType`: `"direct" | "group" | "supergroup" | "channel"`. У каждого чата есть роли участников с числовым `role_id` (owner=1, admin=2, editor=3, direct=4, member=5, viewer=6) и построчной картой прав (`chat:delete`, `member:kick`, `message:send`, ...). Полная таблица — раздел 8.1. Лимиты участников по типу: direct=2, group=500, supergroup=1 000 000, channel=10 000 000 (иначе — обычный `MAX_MEMBERS=1000`).

`ChatFanoutStrategy` (внутреннее, клиенту не отдаётся): `fanout_on_write | active_subscribers | channel_subscribers`.

### 5.2 Чаты — CRUD, join/leave

⚠️ `PATCH /chats/{chat_id}/` — настоящий partial update: поля, которых нет в теле запроса,
остаются как были. Обнулить `name`/`description` через `null` нельзя.

| Метод | Путь | Rate limit | Request | Response |
|---|---|---|---|---|
| GET | `/chats/` | — | Query `GetListUserChatsRequest {limit=50 (≤100), last_chat_id?: UUID, last_activity_at?: datetime}` — курсорная пагинация | `ListChats` |
| POST | `/chats/` | 4/5мин | `CreateChatRequest` | `201`, `ChatDTO` |
| GET | `/chats/{chat_id}/` | — | — | `ChatDetailDTO` |
| PATCH | `/chats/{chat_id}/` | 4/5мин | `UpdateChatRequest` | `200`, `ChatDTO` |
| DELETE | `/chats/{chat_id}/` | 4/5мин | — | `204` |
| POST | `/chats/{chat_id}/join/` | 10/5мин | — | `204` — вступить в публичный чат |
| POST | `/chats/{chat_id}/leave/` | 4/5мин | — | `204` |

⚠️ **Создатель чата (`created_by`) не может выйти через `/leave/`** — `Chat.leave()` сравнивает `user_id` с полем `created_by` (не с ролью!) и при совпадении кидает `403 CHAT_ACCESS_DENIED`. Это ограничение не снимается сменой роли через `PATCH /members/{user_id}/role/` — `created_by` не меняется никаким эндпоинтом, так что создатель заперт в чате навсегда (может только удалить чат целиком через `DELETE /chats/{chat_id}/`, если у него остались права `chat:delete`).

```ts
// CreateChatRequest
{
  name?: string | null;            // ≤ 255 симв.
  description?: string | null;     // ≤ 1024 симв.
  chat_type?: "direct" | "group" | "supergroup" | "channel";  // по умолчанию "direct"
  member_ids?: number[];           // ≤ 100 элементов. Для "direct" ОБЯЗАТЕЛЬНО ровно 1 элемент (иначе MEMBER_LIMIT_EXCEEDED)
  is_public?: boolean;             // по умолчанию false
  admin_only?: boolean;            // по умолчанию false — писать могут только admin+
  slow_mode_seconds?: number;      // 0..86400
  permissions?: Record<string, boolean>;  // override дефолтных прав чата
}
// UpdateChatRequest — все поля опциональны, null = не менять
{ name?, description?, is_public?, admin_only?, slow_mode_seconds?, permissions? }
```

```ts
interface ChatDTO {
  id: string; seq_counter: number; last_activity_at: string | null;
  type: "direct" | "group" | "supergroup" | "channel";
  name: string | null; description: string | null; avatar_s3_key: string | null;
  is_public: boolean; admin_only: boolean; slow_mode_seconds: number;
  permissions: Record<string, boolean>;
  created_by: number; member_count: number; unread_count: number;
  me: MemberChatDTO | null;         // данные о текущем пользователе как участнике (роль, мьют, бан)
  last_read: ReadDetail | null;     // { last_read_message_seq: number, last_read_at: string }
  last_message: MessageDTO | null;  // превью последнего сообщения для списка чатов
}
interface ChatDetailDTO {   // ответ GET /chats/{id}/ — отличается от ChatDTO: вместо unread_count/me/last_read/last_message даёт полный список участников
  id: string; seq_counter: number; last_activity_at: string | null;
  type: "direct" | "group" | "supergroup" | "channel";
  name: string | null; description: string | null; avatar_s3_key: string | null;
  is_public: boolean; admin_only: boolean; slow_mode_seconds: number;
  permissions: Record<string, boolean>;
  created_by: number; member_count: number;
  members: MemberChatDTO[];
}
interface ListChats {   // ответ GET /chats/ — курсорная пагинация, has_next — реальное поле
  has_next: boolean;
  chats: ChatDTO[];
  next_date: string | null;      // передать следующим запросом как last_activity_at
  next_chat_id: string | null;   // передать следующим запросом как last_chat_id
}
interface ReadDetail { last_read_message_seq: number; last_read_at: string }
```

⚠️ **Курсор списка чатов двусоставной**: для следующей страницы нужно передать **оба** значения — `last_activity_at = next_date` и `last_chat_id = next_chat_id` (сортировка `last_activity_at DESC, id DESC`, второй ключ разрешает коллизии по времени).

Ошибки: `400 MEMBER_LIMIT_EXCEEDED` (для direct — если `member_ids.length != 1`), `400 SLOW_MODE_OUT_OF_RANGE`, `403 CHAT_ACCESS_DENIED/NOT_CHAT_MEMBER`, `404 NOT_FOUND_CHAT`.

⚠️ **`409 DIRECT_CHAT_EXISTS` в реальности не возникает** (см. предупреждение в разделе 2.7) — повторный `POST /chats/` с `chat_type: "direct"` на того же собеседника создаст второй, дублирующийся direct-чат. Если клиенту нужна идемпотентность 1:1-чатов, дедуп нужно делать на своей стороне до вызова создания.

### 5.3 Участники чата

| Метод | Путь | Rate limit | Request | Response |
|---|---|---|---|---|
| GET | `/chats/{chat_id}/members/` | — | Query: `limit=50 (≤500), cursor_user_id?, include_presence=false` | `ListMembers` |
| POST | `/chats/{chat_id}/members/` | 30/5мин | `AddMemberRequest {user_id: number, role_id: 1..6 = 5}` | `204` |
| PATCH | `/chats/{chat_id}/members/{user_id}/role/` | — | `ChangeMemberRoleRequest {role_id: 1..6}` | `204` |
| PATCH | `/chats/{chat_id}/members/{user_id}/ban/` | — | `BanMemberRequest {reason?: string, banned_to?: datetime}` | `204` |

⚠️ **Назначить можно только роль строго ниже собственной.** Овнер (level 100) не может
выдать роль `owner` — передача владения чатом не делается сменой роли; админ (90) не может
выдать `owner` или `admin`. Нарушение → `403 CHAT_ACCESS_DENIED`. Неизвестный `role_id`
(вне 1..6) → `422 INVALID_CHAT_ROLE` с `detail: { role_id }`. Это касается и
`POST /members/` (пригласить сразу овнером нельзя), и `PATCH /members/{id}/role/`.

⚠️ `BanMemberRequest.banned_to`: `null` — бан навсегда, дата в прошлом — снятие бана,
дата в будущем — временный бан.
| DELETE | `/chats/{chat_id}/members/{user_id}/` | — | — | `204` (кик) |

```ts
interface MemberChatDTO {
  user_id: number; role_id: number; is_muted: boolean; is_banned: boolean;
  permissions_overrides: Record<string, boolean>;
  profile: ChatProfileDTO | null;   // денормализованный профиль, ходить в /profiles/ не нужно
}
interface MemberDetailDTO {
  user_id: number; role_id: number; is_muted: boolean; is_banned: boolean;
  permissions_overrides: Record<string, boolean>;
  is_online: boolean;
  role: Role;
  profile: ChatProfileDTO | null;
}
interface Role { id: number; name: string; level: number; permissions: Record<string, boolean> }
interface ChatProfileDTO {
  user_id: number;
  username: string | null;
  display_name: string | null;
  avatar_url: string | null;        // presigned URL, генерируется на лету
  avatar_s3_key: string | null;
}
interface ListMembers {   // курсорная пагинация
  members: MemberChatDTO[];
  has_next: boolean;
  next_user_id: number | null;      // передать следующим запросом как cursor_user_id
  presence: MemberPresenceDTO[];    // заполняется только если include_presence=true
}
interface MemberPresenceDTO { user_id: number; is_online: boolean }
```

⚠️ `presence` — **отдельный массив**, а не поле внутри `members`. Клиент сам джойнит по `user_id`; отсутствие записи трактовать как offline.

⚠️ **Забаненные участники по-разному видны в разных эндпоинтах** (несогласованность в текущей реализации, не архитектурное решение):
- `GET /chats/{chat_id}/members/` (постраничный список, `ChatRepository.get_chat_members`) **полностью исключает** забаненных участников — и бессрочно, и временно. Такие пользователи просто не попадут в список, а не придут с `is_banned: true`.
- `GET /chats/{chat_id}/` (`ChatDetailDTO.members`, через `get_by_id(with_members=True)`) отдаёт **всех** участников без этого фильтра — там забаненные будут присутствовать с `is_banned: true`.
- Тот же фильтр применяется к `GET /chats/` — если текущий пользователь сам забанен (перманентно или временно) в каком-то чате, этот чат **пропадёт из его собственного списка чатов** до истечения/снятия бана, без какой-либо отдельной пометки.

Ошибки: `403 NOT_CHAT_MEMBER/CHAT_ACCESS_DENIED`, `404 NOT_FOUND_CHAT`, `409 ALREADY_CHAT_MEMBER`, `400 MEMBER_LIMIT_EXCEEDED`, `400 TOO_LONG_CHAT_ROLE_NAME`.

### 5.4 Сообщения

| Метод | Путь | Rate limit | Request/Query | Response |
|---|---|---|---|---|
| GET | `/chats/{chat_id}/messages/` | — | Query `limit=30 (≤100), cursor_message_seq?` | `MessagesDTO` |
| GET | `/chats/{chat_id}/messages/context/` | — | Query `target_seq (обязателен), limit=40 (≤100)` — сообщения вокруг конкретного `seq` (для перехода "к сообщению") | `MessagesDTO` |
| POST | `/chats/{chat_id}/messages/` | 10/сек (`RATE_LIMIT_MESSAGES_PER_SECOND`) | `SendMessageRequest` + опц. заголовок `Idempotency-Key` | `201`, `MessageDTO` |
| GET | `/chats/{chat_id}/messages/{message_id}/` | — | — | `MessageDTO` |
| PATCH | `/chats/{chat_id}/messages/{message_id}/` | — | `EditMessageRequest {content: string (1..4096)}` | `200`, `MessageDTO` |
| DELETE | `/chats/{chat_id}/messages/{message_id}/` | — | — | `204` |
| POST | `/chats/{chat_id}/messages/forward/` | 10/сек | `ForwardMessageRequest` + опц. заголовок `Idempotency-Key` | `201`, `MessageDTO` |
| POST | `/chats/{chat_id}/messages/read/` | — | `MarkReadRequest {message_seq: number}` | `204` |

```ts
// SendMessageRequest
{
  content?: string | null;          // ≤ 4096 симв.
  reply_to_id?: string | null;      // UUID сообщения, на которое отвечаем
  message_type?: "text" | "image" | "file" | "reply" | "voice" | "video_note";  // по умолчанию "text"
  upload_tokens?: string[];         // UUID'ы слотов вложений (см. 5.5), по умолчанию []
}
// ForwardMessageRequest
{ source_chat_id: string; source_message_id: string; comment?: string | null }  // comment ≤ 4096
// MarkReadRequest
{ message_seq: number }
```

⚠️ `"system"` и `"forward"` клиенту недоступны — их ставит только сервер (`"forward"` появляется
через `POST /messages/forward/`). Попытка отправить их в `POST /messages/` → `422`.

⚠️ **Контент сообщения хранится и отдаётся как есть**, без HTML-экранирования: в `content`
придёт ровно то, что ввёл автор (`<`, `&`, `"`). Экранирование при выводе — забота клиента.

⚠️ **`message_type` расширен**: добавлены `"voice"` и `"video_note"`. Для голосового нужно передать `message_type: "voice"` **и** `upload_tokens` со слотом, запрошенным с `attachment_type: "voice"` (см. 5.5).

**`Idempotency-Key`** (необязательный заголовок при отправке **и пересылке** сообщения — `POST /messages/` и `POST /messages/forward/`): результат кэшируется в Redis на **86 400 сек (24 часа)**; повторный запрос с тем же ключом вернёт закэшированный `MessageDTO` первой отправки. Ключ действует в пределах пары «пользователь + чат» и отдельно для отправки и пересылки. Если предыдущий запрос с тем же ключом ещё обрабатывается (lock на 30 сек) — `409 IDEMPOTENCY_CONFLICT`. Рекомендуется всегда генерировать UUID на клиенте перед отправкой (важно для сценария "нет сети → повтор при реконнекте", чтобы не задублировать сообщение).

```ts
interface MessageDTO {
  id: string; chat_id: string; seq: number; author_id: number | null;
  type: "text" | "image" | "file" | "system" | "reply" | "forward" | "voice" | "video_note";
  content: string | null;
  reply_to_id: string | null;
  forwarded_from_chat_id: string | null;
  forwarded_from_message_id: string | null;
  forwarded_from_author_id: number | null;
  is_edited: boolean;
  created_at: string;
  profile: ChatProfileDTO | null;     // автор уже приложен, отдельный запрос не нужен
  attachments: AttachmentDTO[];
  reply_to: MessageDTO | null;        // вложенный объект оригинала, если это ответ
  forwarded_from: MessageDTO | null;  // вложенный объект оригинала, если это форвард
}
interface MessagesDTO {   // курсорная пагинация, has_next — реальное поле
  messages: MessageDTO[];
  next_cursor: number | null;   // передать следующим запросом как cursor_message_seq
  has_next: boolean;
}
```

**`MessageDTO.reactions`** (`ReactionGroupDTO[]`, см. 5.7.3) присутствует в каждом сообщении списка/деталей/контекста/WS-replay. Обновляется по WS-событию `reaction_update`. Отдельный `GET .../reactions/` нужен только для пагинации списка «кто поставил».

**Порядок и курсор:** `GET /messages/` идёт `direction="backward"` — от новых к старым. `next_cursor` — `seq` последнего (самого старого) элемента страницы, заполняется **только когда `has_next == true`**, иначе `null`.

⚠️ **Никакого окна на редактирование и истории правок в коде нет** (ранее в этом разделе ошибочно указывались несуществующие константы `MAX_EDIT_WINDOW_HOURS`/`MAX_EDIT_HISTORY`). Реальные правила:
- **`PATCH .../messages/{message_id}/` (правка)** — разрешена **только автору сообщения** (`message.author_id == user_id`), без ограничения по времени и без permission-based обхода; чужое сообщение поправить нельзя вообще, даже с `message:delete`/`chat:update`. При несовпадении автора — `403 CHAT_ACCESS_DENIED`. Хранится только текущая версия текста (`is_edited: true`), прошлые версии нигде не сохраняются.
- **`DELETE .../messages/{message_id}/` (удаление)** — разрешено автору **или** любому участнику с правом `message:delete` (роли `owner`/`admin`/`editor`, см. 8.1), в отличие от правки. Мягкое удаление (`is_deleted = true`), контент из БД физически не стирается.

Ошибки: `400 MESSAGE_TOO_LONG/INVALID_MESSAGE/SLOW_MODE_OUT_OF_RANGE`, `403 NOT_CHAT_MEMBER/CHAT_ACCESS_DENIED`, `404 NOT_FOUND_CHAT/NOT_FOUND_MESSAGE`, `409 IDEMPOTENCY_CONFLICT`, `429 SLOW_MODE_LIMIT`.

### 5.5 Вложения — двухшаговая загрузка через presigned PUT (детали отличаются от аватара, см. 9.4)

**Типы вложений.** `AttachmentType`: `"image" | "video" | "file" | "voice" | "video_note"`. `AttachmentStatus`: `"pending" | "success" | "error"`.

| Тип | Макс. размер | Макс. штук на сообщение | Доп. ограничения |
|---|---|---|---|
| `image` | 50 МБ (`MAX_MEDIA_SIZE`) | 10 (`MAX_MEDIA_PER_MESSAGE`) | — |
| `video` | 50 МБ | 10 (общий счётчик с image) | — |
| `file` | 100 МБ (`MAX_FILE_SIZE`) | 1 (`MAX_FILES_PER_MESSAGE`) | — |
| `voice` 🆕 | 20 МБ (`MAX_VOICE_SIZE`) | 1 | ≤ 600 сек; **эксклюзивно** |
| `video_note` 🆕 | 40 МБ (`MAX_VIDEO_NOTE_SIZE`) | 1 | ≤ 60 сек, ≤ 640 px; **эксклюзивно** |

⚠️ **Правило эксклюзивности**: `voice` и `video_note` нельзя смешивать ни друг с другом, ни с media/file в одном запросе. Нарушение → `400 ATTACHMENT_LIMIT_EXCEEDED`.

**Разрешённые MIME** (полные списки из `chat_config`):
- Изображения: `image/jpeg, image/png, image/gif, image/webp, image/heic, image/heif`
- Видео: `video/mp4, video/webm, video/quicktime, video/x-msvideo`
- Файлы: `application/pdf, application/zip, application/x-zip-compressed, application/msword, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, text/plain, text/csv`
- Голосовые: `audio/ogg, audio/opus, audio/mpeg, audio/mp4, audio/aac, audio/webm, audio/x-m4a`
- Видео-кружки: `video/mp4, video/webm, video/quicktime`

**Шаг 1 — `POST /chats/{chat_id}/attachments/upload-requests/`**
```ts
// Request — RequestAttachmentUploadRequest
{
  uploads: Array<{
    filename: string;      // 1..256
    mime_type: string;     // 1..128
    file_size: number;     // > 0
    attachment_type?: "image" | "video" | "file" | "voice" | "video_note" | null;
      // ⚠️ ОБЯЗАТЕЛЬНО для voice и video_note. Без него тип выводится из MIME (image/video/file)
  }>;   // 1..11 элементов (MAX_MEDIA_PER_MESSAGE + MAX_FILES_PER_MESSAGE)
}
// Response 201 — ГОЛЫЙ МАССИВ, не обёрнут в объект
Array<{
  upload_token: string;               // UUID, он же id будущего вложения; нужен на шаге 3 и при отправке сообщения
  upload_url: string;                 // presigned PUT URL, живёт 3600 сек
  attachment_type: "image" | "video" | "file" | "voice" | "video_note";
  expires_in: number;
}>
```
Имя файла санитизируется регуляркой `[^\w.\-]` → `_` и обрезается до 200 символов; ключ в S3 — `chats/{chat_id}/{uuid4}/{clean_filename}`.

⚠️ **Presigned PUT из шага 1 указывает не на финальный бакет.** Загрузка идёт в промежуточный бакет `chat-pending-attachments` (`ATTACHMENT_BUCKET_PENDING`). Только после успешной фоновой валидации (шаг 3) файл копируется в `chat-attachments` (`ATTACHMENT_BUCKET`) и удаляется из pending-бакета. Для клиента это прозрачно (просто PUT по выданному URL), но если что-то читает/пишет в S3/MinIO напрямую в обход API — важно не путать эти два бакета.

**Шаг 2 — `PUT <upload_url>`** напрямую в S3/MinIO (минуя бэкенд), `Content-Type: <mime_type файла>`, тело — сырые байты файла целиком. Никакого multipart, никаких дополнительных полей.

**Шаг 3 — `POST /chats/{chat_id}/attachments/upload-requests/confirm/`**
```ts
// Request — ConfirmAttachmentUploadRequest
{ upload_tokens: string[] }   // 1..11 элементов, те же токены из шага 1
// Response 202 Accepted, пустое тело — обработка асинхронная (fire-and-forget)
```
После `202` бэкенд в фоне валидирует реальное содержимое файла и заполняет `width/height/duration_seconds`, переводя статус `pending → success` (или `error`). Готовность отслеживается через WS-событие `attachment_success` (раздел 7.4) — в его `payload.tokens` попадут завершённые `upload_token`. Отдельного WS-события на ОШИБКУ обработки в протоколе нет — для проверки неудачи ориентируйтесь на `attachment_status: "error"` после отправки сообщения.

Внутри фонового воркера (`ProccessAttachmentsCommandHandler`) причина падения в `error` может быть любой из: несовпадение размера с заявленным, несовпадение реального MIME (magic bytes) с заявленным, инфраструктурная ошибка стораджа, а для `voice`/`video_note` — дополнительно любая из `AttachmentRejectionReason` (`size_limit_exceeded`, `duration_limit_exceeded`, `resolution_limit_exceeded` — только video_note, `frame_rate_limit_exceeded` — только video_note, `metadata_unreadable`, `probe_timeout`, `invalid_media` — напр. voice без аудиодорожки или с видеодорожкой, video_note не с одной видеодорожкой). Конкретная причина **никуда клиенту не передаётся** — только `attachment_status: "error"`, различить причины на фронте нельзя.

**Шаг 4 — отправить сообщение**, передав `upload_tokens` из шагов 1/3 в `POST /chats/{chat_id}/messages/` (раздел 5.4) с корректным `message_type`.

**Скачивание:** `GET /chats/{chat_id}/messages/{message_id}/attachments/{attachment_id}/download-url/` → `AttachmentDownloadUrlDTO { attachment_id: string; url: string; expires_in: number }` (ссылка живёт 300 секунд, генерировать заново при истечении).

```ts
interface AttachmentDTO {
  id: string; message_id: string | null; chat_id: string; uploader_id: number;
  attachment_type: "image" | "video" | "file" | "voice" | "video_note";
  attachment_status: "pending" | "success" | "error";
  url: string | null; url_expires_in: number | null;
  s3_key: string; mime_type: string; original_filename: string; size: number;
  width: number | null; height: number | null; duration_seconds: number | null;
  created_at: string;
}
```

⚠️ `url` живёт 300 секунд — кэшировать нужно скачанный файл (ключ — `s3_key`), а не сам URL.

Ошибки: `400 ATTACHMENT_VALIDATION/INVALID_UPLOAD_TOKEN/ATTACHMENT_LIMIT_EXCEEDED/EMPTY_ATTACHMENT_UPLOAD_REQUEST`, `403 CHAT_ACCESS_DENIED/NOT_CHAT_MEMBER`, `404 NOT_FOUND_CHAT/ATTACHMENT_NOT_FOUND`.

### 5.6 Звонки (LiveKit)

| Метод | Путь | Rate limit | Request | Response |
|---|---|---|---|---|
| POST | `/chats/{chat_id}/calls/join/` | 10/5мин | — | `200`, `JoinTokenDTO` |
| POST | `/chats/{chat_id}/calls/participants/{user_id}/mute/` | 4/5мин | `MuteParticipantRequest {muted: boolean = true}` | `204` |

```ts
interface JoinTokenDTO { token: string; slug: string; livekit_url: string }
interface LiveKitParticipantsDTO { identity: string; name: string; state: number; joined_at: number }
```
`token` — LiveKit access-токен (TTL `ROOM_TOKEN_TTL = 3600`), `livekit_url` — адрес LiveKit-сервера (`wss://...`) для подключения через LiveKit Flutter SDK (`livekit_client`). Максимум участников — `ROOM_MAX_PARTICIPANTS = 100`.

⚠️ Эндпоинта "завершить/покинуть звонок" в REST нет — выход выполняется средствами LiveKit SDK (disconnect от комнаты). События `call_started/call_ended/call_joined/call_left` объявлены в `WSEventType`, но бэкендом **не публикуются**.

Ошибки: `502 LIVEKIT_ERROR {reason}`, `502 LIVEKIT_UNAUTHORIZED`, `404 NO_ACTIVE_CALL`, `409 ACTIVE_CALL_EXISTS`.

### 5.7 Реакции на сообщения 🆕

#### 5.7.1 Эндпоинты

Базовый префикс: `/chats/{chat_id}/messages/{message_id}/reactions`

| Метод | Путь | Rate limit | Request | Response |
|---|---|---|---|---|
| GET | `.../reactions/` | — | Query `emoji?: string (1..32), limit=50 (≤100), cursor_user_id?: number (≥1)` | `200`, `MessageReactionsDTO` |
| PUT | `.../reactions/` | 10/сек (`RATE_LIMIT_REACTIONS_PER_SECOND`) | `{ "reactions": string[] }` | `204` — заменить весь набор реакций пользователя (set-семантика) |
| DELETE | `.../reactions/` | 10/сек | — | `204` — снять все свои реакции |
| PUT | `.../reactions/{emoji}/` | 10/сек | — | `204` — добавить одну реакцию |
| DELETE | `.../reactions/{emoji}/` | 10/сек | — | `204` — снять одну реакцию |

`{emoji}` — path-параметр, строка 1..32, **обязательно URL-encoded** (`👍` → `%F0%9F%91%8D`).

#### 5.7.2 Семантика (Telegram-like)

- Пользователь может поставить **несколько** разных эмодзи на одно сообщение — до `MAX_REACTIONS_PER_USER_PER_MESSAGE = 3`.
- `PUT .../reactions/{emoji}/` — добавляет эмодзи к набору пользователя. Повтор того же эмодзи — no-op, ответ `204`.
- `DELETE .../reactions/{emoji}/` — снимает конкретный эмодзи. Снятие отсутствующего — no-op, `204`.
- `PUT .../reactions/` с телом `{ "reactions": ["👍","🔥"] }` — **полная замена** набора пользователя (как `messages.sendReaction` в Telegram). Пустой список = снять всё.
- Каждое результирующее изменение публикует **ровно одно** событие `chats.message.reaction_updated` на сообщение — со снимком всех групп (не дельтой).
- Разрешён только курированный каталог эмодзи (`app/chats/reactions/catalog.py`, ~73 шт.). Плюс настройки чата (5.7.5).

#### 5.7.3 Ответ GET

```ts
interface ReactionGroupDTO {
  emoji: string;
  count: number;
  version: number;            // монотонная версия группы (для идемпотентной сверки на клиенте)
  reacted_by_me: boolean;
  recent_user_ids: number[];  // до REACTION_RECENT_USERS_LIMIT (3) последних реагировавших, для аватарок
}
interface MessageReactionsDTO {
  message_id: string;                 // UUID
  groups: ReactionGroupDTO[];         // всегда: сводка по ВСЕМ эмодзи сообщения, сортировка count DESC, emoji ASC
  emoji: string | null;               // эхо query-параметра
  users: number[];                    // user_id, непустой ТОЛЬКО если передан ?emoji=
  has_next: boolean;
  next_user_id: number | null;        // передать следующим запросом как cursor_user_id
}
```
Два режима одного эндпоинта:
1. **Без `?emoji=`** — только `groups` (для «чипсов» под сообщением), `users = []`.
2. **С `?emoji=👍`** — дополнительно постранично отдаёт список проголосовавших (шторка «кто поставил»).

Реакции также приходят **прямо в `MessageDTO.reactions`** (`ReactionGroupDTO[]`) в списке сообщений, деталях, контексте и в WS-replay (`ws.history`) — отдельный GET нужен только для пагинации «кто поставил».

#### 5.7.4 Лимиты и ошибки

- `MAX_DISTINCT_REACTIONS_PER_MESSAGE = 20` — максимум различных эмодзи на сообщение.
- `MAX_REACTIONS_PER_USER_PER_MESSAGE = 3` — максимум эмодзи от одного пользователя.
- `MAX_REACTION_LENGTH = 32`.

| code | HTTP | detail | Когда |
|---|---|---|---|
| `INVALID_REACTION` | 400 | `{ "emoji": string }` | эмодзи не входит в каталог |
| `REACTION_NOT_ALLOWED` | 400 | `{ "emoji": string, "allowed": string[] }` | чат в режиме `some`, эмодзи не в белом списке |
| `REACTIONS_DISABLED` | 403 | `{ "chat_id": string }` | в чате `reactions_mode = "none"` |
| `TOO_MANY_REACTIONS` | 400 | `{ "limit": number, "scope": "user" \| "message" }` | превышен лимит |
| `CHAT_ACCESS_DENIED` | 403 | `{ "chat_id": string, "requester_id": number }` | участник в муте |
| `NOT_FOUND_CHAT` | 404 | `{ "chat_id": string }` | не участник чата |
| `NOT_CHAT_MEMBER` | 403 | `{ "chat_id": string, "user_id": number }` | участник забанен |
| `NOT_FOUND_MESSAGE` | 404 | `{ "message_id": string }` | нет сообщения / другой чат / удалено |

#### 5.7.5 Настройки реакций на уровне чата

`ChatDTO` / `ChatDetailDTO` содержат:
- `reactions_mode: "all" | "some" | "none"` (по умолчанию `"all"`);
- `allowed_reactions: string[]` — белый список эмодзи, применяется при `mode = "some"`.

Меняются через `PATCH /chats/{chat_id}/` (`chat:update`), поля `reactions_mode`, `allowed_reactions`. Изменение уходит в `chat_updated`.

#### 5.7.6 WS-событие

Доменное событие `chats.message.reaction_updated` → WS-тип `reaction_update`. Payload **не содержит `MessageDTO`** — только компактный снимок реакций. При включённом коалесинге (`REACTIONS_COALESCE_ENABLED`, по умолчанию) всплеск реакций на «вирусном» сообщении схлопывается в ≤ 1 рассылку за `REACTIONS_COALESCE_WINDOW_MS` (500 мс), снимок всегда финальный.

```ts
{
  type: "reaction_update",
  channel: string,           // chat_id
  ts: string,
  payload: {
    event_id: string;          // ключ дедупликации
    event_name: "chats.message.reaction_updated",
    event: { message_id: string; actor_id: number; action: string },
    message: null,
    reaction: {
      message_id: string;
      chat_id: string;
      actor_id: number;      // кто вызвал изменение
      action: "add" | "remove" | "replace" | "update";
      groups: ReactionGroupDTO[];   // полный текущий набор групп; reacted_by_me тут всегда false
    }
  },
  delivery: { require_subscription: boolean; recipients: number[] }
}
```

Обработка: заменить группы реакций у локального сообщения `message_id` на `reaction.groups`. `reacted_by_me` в этом событии не персонализируется — клиент трекает свой выбор оптимистично (или сверяется через GET). После переподключения актуальные реакции для видимых сообщений приходят в `ws.history` / перезапросом списка сообщений.


## 6. Чаты — WebSocket

⚠️ Это самый важный раздел документа для реализации чата на Flutter — в предыдущей версии доков он был описан на 5% от реального объёма (были упомянуты только `ws.ready` и `ws.error`). Ниже — полный протокол, вычитанный построчно из `app/chats/routes/v1/ws.py`, `app/chats/commands/websockets/*.py`, `app/chats/dtos/delivery.py`, `app/chats/services/delivery_router.py`, `app/chats/models/{chat,message}.py`.

### 6.1 Подключение

```
WS  {BASE_URL}/api/v1/chats/ws/?token=<access_token>
```

Способы передать токен (любой из трёх, проверяются в этом порядке):
1. Query-параметр `?token=<access_token>` или `?access_token=<access_token>`
2. Заголовок `Authorization: Bearer <access_token>` (если используемая WS-библиотека умеет слать заголовки при handshake)
3. `Sec-WebSocket-Protocol: bearer.<access_token>` или `bearer <access_token>`

Для Flutter практичнее всего — **query-параметр** (пакет `web_socket_channel` не всегда легко даёт слать кастомные заголовки на всех платформах, а query-параметр работает везде одинаково).

Токена нет/невалиден → сервер закрывает соединение кодом **1008** ("missing token") ещё ДО `websocket.accept()` — то есть это будет просто разрыв соединения на этапе handshake, без единого JSON-сообщения.

**Доп. query-параметры при подключении:**
- `device_id` (строка, опционально) — если не передан, берётся из JWT или подставляется `"unknown"`.
- `initial_chat_id` + `initial_last_seq` (опционально, **оба сразу или ни одного**) — если переданы, сразу после `ws.ready` сервер сам выполнит `subscribe` на этот чат с этим `last_seq`, экономя один round-trip при "открыл чат → сразу открыл экран сообщений".

Пример полного URL: `wss://api.example.com/api/v1/chats/ws/?token=eyJhbGciOi...&initial_chat_id=550e8400-...&initial_last_seq=42`

**Subprotocol:** если клиент предлагает `Sec-WebSocket-Protocol: chat.v1`, сервер его подтвердит; необязательно, но можно указать для строгости.

### 6.2 Жизненный цикл соединения и heartbeat

1. Сразу после установки соединения сервер шлёт `ws.ready` (см. 6.3).
2. Каждые `heartbeat_interval` секунд (по умолчанию **30**) сервер сам присылает `{"type": "ws.ping", "connection_id": "...", "ts": "..."}`.
3. Клиент должен отвечать **любым** валидным сообщением (в идеале `{"op": "pong"}`) не реже, чем раз в `heartbeat_timeout` секунд (по умолчанию **75**) — иначе сервер закроет соединение кодом **1001** ("heartbeat timeout"). Практически: любое сообщение от клиента (включая `subscribe`/`ping`/что угодно) продлевает таймаут, но для чистоты протокола лучше явно отвечать `pong` на каждый `ws.ping`.
4. Максимум **2 одновременных соединения** на пользователя (`WS_MAX_CONNECTIONS_PER_USER=2`). Третье подключение вызовет закрытие **самого старого** соединения кодом **1012** ("connection limit exceeded"). Это значит: если пользователь открывает приложение на третьем устройстве/вкладке, где-то на другом устройстве WS отвалится — стоит реализовать авто-реконнект с обработкой этого кода.
5. Максимальный размер входящего фрейма от клиента — 64 КБ (`WS_MAX_CLIENT_FRAME_BYTES=65536`).

**Рекомендованная логика реконнекта:** при разрыве — переподключиться, затем отправить `resume` со словарём `{chat_id: last_known_seq}` по всем чатам, которые сейчас открыты/видны в UI (максимум 20 чатов за раз — см. 6.3).

### 6.3 Команды клиент → сервер

Отправляются как `{"op": "...", ...}` текстовым WS-фреймом (JSON).

| `op` | Поля | Что делает |
|---|---|---|
| `subscribe` | `chat_id: string (обязательно)`, `last_seq?: number` | Подписаться на события конкретного чата. Если передан `last_seq`, сервер дополнительно пришлёт `ws.history` — все сообщения, случившиеся после этого seq (докачка пропущенного). |
| `unsubscribe` | `chat_id: string (обязательно)` | Отписаться от чата (например, экран чата закрыт). |
| `resume` | `cursors: Record<string, number>` — `{chat_id: last_seq}` | Массовая переподписка после реконнекта. **Максимум 20 ключей** — при превышении обработчик выбрасывает необработанное исключение `MAX_LIMIT_CURSOR`, которое **не** оборачивается в аккуратный `ws.error` (в отличие от остальных ошибок этого раздела) — на практике может привести к обрыву соединения. Не отправлять больше 20 курсоров за раз. |
| `ping` | — | Проверка живости соединения по инициативе клиента, сервер ответит `ws.pong`. |
| `pong` | — | Ответ на серверный `ws.ping` (обновляет heartbeat-таймер на сервере). |

```ts
// Общая форма исходящей команды
interface WSClientCommand {
  op: "subscribe" | "unsubscribe" | "resume" | "ping" | "pong";
  chat_id?: string;
  last_seq?: number;
  cursors?: Record<string, number>;
}
```

### 6.4 События сервер → клиент

Общий конверт для событий, доставляемых через Redis stream на WS-gateway:
```ts
interface DeliveryData {
  require_subscription: boolean;        // gateway дополнительно проверяет активную подписку на чат
  recipients: number[];                 // user_id получателей внутри конкретной stream-записи
}

interface MessagePayloadWS {
  event_id: string;                     // id доменного события — ключ дедупликации на клиенте
  event_name: string;                   // "chats.message.readed", "chats.member.kicked", ...
  event: Record<string, any>;           // ДЕЛЬТА события: поля, специфичные для этого типа (см. таблицу)
  message: MessageDTO | null;           // полный DTO сообщения — только для new_message/message_edited
  reaction?: ReactionUpdateWSDTO | null; // заполнен только для type = "reaction_update" (см. 5.7.6)
}

interface DeliveryDTO {
  type: string;                         // см. таблицу ниже
  channel: string;                      // chat_id
  payload: MessagePayloadWS | AttachmentSuccessPayload;
  delivery: DeliveryData;
  ts: string;                           // ISO datetime
}
```

Клиент получает фрейм без блока `delivery` — gateway разворачивает конверт и шлёт
`{ type, channel, payload, ts, enqueued_at }`.

⚠️ Доставка **at-least-once** (Redis Streams + xautoclaim переподхватывает записи упавшего
gateway), поэтому один и тот же кадр может прийти дважды — дедуплицируйте по
`payload.event_id`.

`chat_id` в дельте не дублируется — он всегда в `channel`. Полный снимок сообщения приходит
только там, где он реально нужен (`new_message`, `message_edited`); остальным событиям
достаточно дельты, поэтому у них `message: null` — рефетч по REST не требуется.

#### Доменные события (`type`) и точная форма `payload`

| `type` | Когда | `payload.event` (дельта) | `payload.message` |
|---|---|---|---|
| `new_message` | Новое сообщение в чате | `{ message_id, seq, sender_id, message_type }` | полный `MessageDTO` с profile, attachments (с download-ссылками), reply_to, forwarded_from, reactions |
| `message_edited` | Сообщение отредактировано | `{ message_id, seq, modified_by }` | полный `MessageDTO` — заменить локальное по `message.id` |
| `message_deleted` | Сообщение удалено | `{ message_id, seq, deleted_by }` | `null` — сообщения уже нет в БД, удаляйте локальное по `event.message_id` |
| `messages_read` | Кто-то прочитал сообщения до seq X | `{ seq, reader_id }` | `null` — двигать «прочитано» для `reader_id` до `seq` |
| `member_joined` | Новый участник добавлен/вступил | `{ user_id, role_id }` | `null` |
| `member_left` | Участник вышел сам | `{ user_id }` | `null` |
| `member_kick` | Участника кикнули | `{ target_user_id, requester_id }` | `null` |
| `member_banned` | Участника забанили/разбанили | `{ target_user_id, requester_id, ban }` — `ban: true` бан, `false` разбан | `null` |
| `chat_created` | Чат создан | `{ created_by, name, member_ids, chat_type, member_count }` | `null` |
| `chat_updated` | Изменены настройки чата | `{ updated_by, name, description, is_public, admin_only, slow_mode_seconds, permissions, reactions_mode, allowed_reactions }` | `null` |
| `chat_deleted` | Чат удалён | `{ deleted_by }` | `null` — убрать чат из списка |
| `reaction_update` | Поставили/сняли/заменили реакцию на сообщении | `{ message_id, actor_id, action }` | `null`; снимок групп — в `payload.reaction.groups` (полный текущий набор). Под нагрузкой рассылки коалесятся (окно 500 мс). Подробно — 5.7.6 |
| `attachment_success` | Вложение(я) успешно обработаны после `confirm/` (шлётся лично пользователю-загрузчику, не всей подписке чата) | — | `payload` здесь другой: `AttachmentSuccessPayload { user_id, chat_id, tokens }`; `delivery.require_subscription=false`, `recipients=[user_id]` |

`member_kick`, `member_left` и `member_banned` (`ban: true`) дополнительно доставляются
адресно самому исключённому участнику — его уже нет в чате, и обычным фан-аутом он не
покрывается. Ему это событие может прийти и без активной подписки на чат.

**Определены, но реально нигде не публикуются** (есть в `WSEventType`, но ни одного места публикации в коде): `typing_start`, `typing_stop`, `call_started`, `call_ended`, `call_joined`, `call_left`. Не полагайтесь на их получение — заложить обработку на будущее можно, но сейчас бэкенд их не шлёт.

#### Служебные события (`ws.*`)

| `type` | Форма | Когда |
|---|---|---|
| `ws.ready` | `{ type, payload: { connection_id: string; gateway_id: string; heartbeat_interval: number; heartbeat_timeout: number; reconnect: { mode: "last_seq_per_chat"; op: "resume" } } }` | Сразу после подключения |
| `ws.subscribed` | `{ type, chat_id: string, payload: { last_seq: number \| null }, ts }` | Ответ на `subscribe`/`resume` |
| `ws.unsubscribed` | `{ type, chat_id: string, payload: {}, ts }` | Ответ на `unsubscribe` |
| `ws.history` | `{ type, chat_id: string, payload: { after_seq: number; messages: MessageDTO[]; has_more: boolean; next_last_seq: number }, ts }` | Досылается после `ws.subscribed`, только если был передан `last_seq`/курсор. `messages` — полные `MessageDTO` (раздел 5.4), с уже прикреплёнными download-ссылками для вложений. |
| `ws.pong` | `{ type: "ws.pong", payload: {} }` | Ответ на клиентский `{"op": "ping"}` |
| `ws.ping` | `{ type: "ws.ping", connection_id: string, ts }` ⚠️ без обёртки `payload` | Проактивный heartbeat-пинг от сервера, раз в `heartbeat_interval` сек |
| `ws.error` | { type: "ws.error", code: "BAD_COMMAND" \| "BAD_FRAME" \| "NOT_CHAT_MEMBER", detail: string, ts: string } ⚠️ без payload | `subscribe`/`resume` на чат, где отправитель не состоит (или забанен) или Нераспарсенная/невалидная команда от клиента |

### 6.5 Практическая схема работы для Flutter-клиента

1. Установить соединение с `?token=...`. Слушать `ws.ready`, сохранить `heartbeat_interval`/`heartbeat_timeout`.
2. На каждый экран чата — слать `{"op": "subscribe", "chat_id": "...", "last_seq": <последний известный seq из локального кэша>}`.
3. При получении `new_message`/`message_edited` — брать готовое сообщение из `payload.message`. Для остальных доменных событий (`message_deleted`, `messages_read`, `member_*`, `chat_*`) `payload.message` = `null`, а всё нужное лежит в дельте `payload.event` (см. 6.4) — рефетч не нужен. Для `reaction_update` — брать `payload.reaction` (компактный снимок групп, см. 5.6.6). Любое доменное событие дедуплицировать по `payload.event_id`: доставка at-least-once.
4. На `ws.ping` отвечать `{"op": "pong"}`.
5. При разрыве соединения — переподключиться с экспоненциальным backoff, затем отправить `resume` с курсорами по всем открытым в UI чатам (≤20).
6. При закрытии с кодом `1012` — значит открыто больше 2 соединений на аккаунт; просто переподключиться нормально (не ошибка, а следствие лимита).
7. Не полагаться на `typing_start/stop` и `call_*` события — сейчас не реализованы бэкендом.


## 7. Уведомления

⚠️ Модуль полностью отсутствовал в предыдущей версии документа. Пути — `/devices` и `/notifications` (не вложены друг в друга).

### 7.1 Регистрация устройства для push

**`POST /devices/`** 🔒
```ts
// Request (CreateUserDeviceRequest)
{ platform: "IOS" | "WEB" | "ANDROID"; token: string; device_name: string }
```
`token` — это токен FCM/APNs устройства. **Response `201`**, тело пустое.

### 7.2 Список уведомлений

**`GET /notifications/`** 🔒 — Query: `{ is_read?: boolean; page=1; page_size=20; sort="created_at:desc" }`.

**Response `200`**: `PageResult<NotificationDTO>` (только 4 поля пагинации, см. 1.5).

```ts
interface NotificationDTO {
  id: number; user_id: number;
  type: "system" | "chat";
  title: string;
  message: string | null;
  payload: Record<string, unknown>;   // произвольная структура, зависит от type (например для чата может содержать chat_id/message_id — конкретная схема на бэке не типизирована жёстко, обрабатывать defensively)
  is_read: boolean;
  created_at: string; updated_at: string;
}
```

### 7.3 Счётчик непрочитанных

**`GET /notifications/unread_count/`** 🔒 → `{ unread_count: number }`.

### 7.4 Отметить прочитанным

**`PATCH /notifications/{notification_id}/read/`** 🔒 — Request: `{ is_read: boolean = true }` (можно и снять отметку, передав `false`). Response `200`, тело пустое. Ошибки: `403 NOTIFICATION_ACCESS_DENIED`, `404 NOT_FOUND_NOTIFICATION`.

**`PATCH /notifications/read_all/`** 🔒 ⚠️ — Response `200`, тело — **голое число** (не объект!), например `7` — количество отмеченных уведомлений.


## 8. Сводка ролей и прав

Три независимые системы ролей в проекте — не путать между собой: системные роли auth (раздел 3.16), роли участников чата (8.1), роли участников проекта (8.2). Все три идентифицируются разными числовыми id в разных таблицах.

### 8.1 Роли чата (`ChatRolesEnum`) — полная матрица прав

| Право \ Роль | owner (id=1) | admin (id=2) | editor (id=3) | direct (id=4) | member (id=5) | viewer (id=6) |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `chat:delete` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `chat:update` | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `chat:get` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `member:invite` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `member:kick` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `member:ban` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `member:mute` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `role:change` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `permission:update` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `message:read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `message:send` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `message:delete` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `message:pin` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `message:send_admin_only` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `settings:update` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `settings:get` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `channel:publish` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `channel:edit` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `channel:manage_subscribers` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `slowmode:bypass` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `call:join` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `call:mute_member` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `call:end` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |

`role_id=4` ("direct") — специальная роль для участников личных (1:1) чатов, назначается обоим при создании direct-чата. При создании group/supergroup создатель получает `role_id=1` (owner), остальные добавленные — `role_id=5` (member) по умолчанию. При создании channel создатель получает `role_id=1`, остальные — `role_id=6` (viewer, "подписчик"). Значение по умолчанию для `AddMemberRequest.role_id` — `5`.

Значения из `chat.permissions` (поле `ChatDTO.permissions`) — это **override-словарь на уровне самого чата** (задаётся при создании/обновлении чата, см. `CreateChatRequest.permissions`/`UpdateChatRequest.permissions`), плюс у каждого участника есть свой `MemberChatDTO.permissions_overrides` — персональный override поверх роли. Итоговое право = роль → override чата → персональный override участника (более специфичный побеждает; конкретный порядок слияния решает `ChatAccessService` на бэкенде).

### 8.2 Системные роли (auth) — см. также раздел 3.16

| Роль | `security_level` | Ключевая особенность |
|---|---|---|
| `super_admin` | 10 | Обходит вообще все проверки прав (`is_system_user`) |
| `system_admin` | 9 | Управление пользователями/ролями, без `system:*`-полного доступа |
| `user` | 1 | Роль по умолчанию, без специальных прав — обычный пользователь приложения |


## 9. Гайд по реализации на Flutter

Этот раздел — не часть спецификации API, а рекомендации по архитектуре клиента с учётом всех особенностей, перечисленных выше.

### 9.1 HTTP-слой

- Использовать `dio` (не голый `http`) — нужны интерцепторы для refresh-логики и единообразной обработки ошибок.
- **Базовый интерцептор путей**: всегда добавлять `/` в конец пути перед отправкой (или просто дисциплинированно писать пути с `/` в конце во всех местах кода — `redirect_slashes=False` не прощает ошибок).
- **Интерцептор ошибок**: разбирать `error.response.data` по схеме раздела 2 — сначала проверить `statusCode == 429` (формат `{detail: "..."}`), иначе читать `data['error']['code']`, `data['error']['message']`, `data['error']['detail']`. `code == "VALIDATION"` → `detail` это список, `code` — что угодно другое → `detail` это объект (может быть `null`).
- **Refresh-интерцептор**: поскольку access-токен живёт всего 5 минут, реализовать `QueuedInterceptorsWrapper` в `dio`, который на `401`/`400 EXPIRED_TOKEN` сам вызывает `POST /auth/refresh/`, получает новый `access_token` и повторяет исходный запрос. Использовать очередь (mutex/lock), чтобы при параллельных запросах не улетело несколько одновременных `refresh` подряд.
- **`POST /auth/login/`** — отправлять как `FormData`/`application/x-www-form-urlencoded` с полями `username`+`password`, НЕ как JSON.

### 9.2 Refresh-токен и cookies — разница между платформами

Сервер выставляет `refresh_token` как `HttpOnly + Secure + SameSite=Strict` cookie, без явного `max-age` (сессионная cookie по атрибутам, хотя токен внутри логически живёт 60 дней).

- **Android/iOS (мобильное приложение через `dio`)**: подключить `dio_cookie_manager` + `cookie_jar` (`PersistCookieJar`, чтобы cookie переживала перезапуск приложения — иначе, будучи "сессионной", она может не сохраниться между запусками некоторыми реализациями jar). `Secure=true` требует, чтобы `BASE_URL` был `https://` — на локальной разработке через `http://` cookie может не долететь до сервера/не сохраниться в некоторых http-клиентах, которые уважают этот флаг. Уточнить у бэкенд-команды тестовый HTTPS-адрес или использовать `Secure`-совместимый локальный прокси (например через `ngrok`/самоподписанный сертификат), либо попросить временно отключить `Secure` на деве.
- **Flutter Web**: браузер сам управляет cookie по правилам `SameSite=Strict` — если фронтенд крутится на другом домене/порте, чем API, куки **не будет отправляться** при кросс-доменных запросах, и `POST /auth/refresh/` перестанет работать в принципе. Для веб-сборки нужно либо разместить фронт и API на одном домене (например, API под `/api` того же origin через reverse-proxy), либо держать в уме, что на вебе `refresh` может не работать "из коробки" при разнесённых доменах — это архитектурное решение нужно согласовать с бэкенд-командой (например, включить `BACKEND_CORS_ORIGINS` + `allow_credentials=True`, что уже сделано на бэке, но `SameSite=Strict` всё равно блокирует большинство кросс-сайтовых сценариев в современных браузерах).

### 9.3 Пагинация — два разных паттерна

1. **Обычные списки** (`PageResult<T>`) — считать `has_next`/`total_pages` вручную на клиенте по `total`/`page`/`page_size`. Использовать для: профилей, проектов, позиций, заявок, ролей/прав auth, ролей проекта, сессий, пользователей, уведомлений.
2. **Курсорные списки чатов** (`ListChats`, `MessagesDTO`, `ListMembers`) — `has_next` уже готовое поле; для следующей "страницы" использовать `next_chat_id`/`next_date`, `next_cursor`, `next_user_id` соответственно, не `page`.

### 9.4 Загрузка файлов — общий механизм, но детали разные

Оба флоу — presigned **PUT** (сырые байты файла телом запроса, без multipart), но реализованы независимо и отличаются деталями:

| | Аватар профиля | Вложение в чат |
|---|---|---|
| Presign-эндпоинт | `POST /profiles/avatar/presign/` | `POST /chats/{id}/attachments/upload-requests/` |
| Что слать на presign | `{ filename }` | `{ uploads: [{ filename, mime_type, file_size, attachment_type? }] }`, до 11 файлов за раз |
| TTL presigned URL | 90 секунд | 3600 секунд |
| Подтверждение | `POST /profiles/avatar/upload_complete/` — `{ file_key }` | `POST /chats/{id}/attachments/upload-requests/confirm/` — `{ upload_tokens }` |
| Валидация типа/размера | только асинхронно, после подтверждения (в фоне) | синхронно на presign по `mime_type`/`file_size` из запроса + асинхронно после подтверждения (доуточнение `width/height/duration`) |
| Как узнать результат | переопросить `GET /profiles/{id}/` — новый `avatars`, либо файл не появится | WS-событие `attachment_success` / `attachment_status: "error"` на вложении |
| Результат | Появляется в `ProfileDTO.avatars` | Прикрепить `upload_token` к сообщению в `POST /chats/{id}/messages/` |

### 9.5 WebSocket-клиент

- Пакет `web_socket_channel` (или `IOWebSocketChannel.connect` на io-платформах, если нужны кастомные заголовки).
- Подключаться на `wss://{host}/api/v1/chats/ws/?token=<access>` — токен обновлять при реконнекте (использовать актуальный access-токен на момент подключения, не кэшировать старый).
- Отдельный сервис-синглтон с очередью команд, стейт-машиной `connecting → ready → subscribed(chat_id)*`, и обработкой всех кодов закрытия (`1001` heartbeat timeout, `1008` bad/missing token, `1012` connection limit) с авто-реконнектом и `resume`.
- Хранить `Map<chatId, lastSeq>` локально (например в стейте Riverpod/Bloc или простой персистентный кэш) — использовать для `subscribe.last_seq` и для формирования `resume.cursors` (не больше 20 ключей за раз — если открытых чатов в кэше больше, слать только самые "горячие"/недавно посещённые).
- Помнить, что `new_message`/`message_edited`/`message_deleted` — это **уведомления, не данные**. Дизайн стора сообщений должен уметь: (a) оптимистично добавлять своё отправленное сообщение сразу после успешного REST-ответа `POST /messages/`, (b) при чужом `new_message` — либо дозапросить сообщение по id, либо просто рефетчить хвост через `GET /messages/`.

### 9.6 Разграничение прав в UI

Строить видимость кнопок (пригласить/кикнуть/забанить/удалить чат и т.п.) на основе:
- Для чата: `MemberChatDTO.permissions_overrides` текущего пользователя, объединённый с матрицей роли (раздел 8.1) и `chat.permissions`.
- Для системных админ-функций (управление пользователями/ролями): требуемые права из таблиц разделов 3.10–3.14 — если у пользователя нет системной роли с этими правами, соответствующие экраны/пункты меню не показывать вовсе.

### 9.7 Чек-лист перед тем, как считать интеграцию готовой

- [ ] Все пути заканчиваются на `/`
- [ ] `login` отправляется как form-urlencoded с полями `username`/`password`
- [ ] Ошибки читаются из `body.error.code`, кроме 429 (`body.detail`)
- [ ] Реализован refresh-интерцептор на 5-минутное истечение токена
- [ ] `has_next`/`total_pages` считаются на клиенте для обычных списков
- [ ] И аватар, и вложения чата грузятся через presigned PUT, но с разным TTL ссылки (90 сек / 3600 сек) и разным моментом валидации (см. 9.4)
- [ ] WS обрабатывает все перечисленные в 6.4 типы событий
- [ ] `new_message`/`message_edited`/`message_deleted` не рендерятся напрямую из WS-payload
- [ ] `resume` никогда не отправляется больше чем с 20 курсорами
- [ ] Учтена структура `avatars` (4 размера × 3 формата), а не плоский `{url}`
