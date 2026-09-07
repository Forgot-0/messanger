# FastAPI Template

Production-ready модульный монолит на FastAPI: асинхронный SQLAlchemy 2.0, CQRS-style команды/запросы через собственный медиатор, Dependency Injection на [Dishka](https://github.com/reagento/dishka), событийная модель на **transactional outbox + CDC (Postgres WAL → Debezium → Kafka)**, готовые сервисы (кэш, очереди, почта, S3-хранилище, WebSocket-gateway) и полный набор наблюдаемости (Prometheus, Grafana, Loki).

Вдохновлён [Starter Kit](https://github.com/arctikant/fastapi-modular-monolith-starter-kit).

**Что описано в этом README.** Только два каркасных пакета: `app/core` — инфраструктура (БД, DI, медиатор, фильтры, события/outbox, брокеры, очереди, WebSocket, наблюдаемость) и `app/auth` — **эталонный (reference) модуль**, показывающий, как должен быть устроен любой новый модуль (модели, фильтры, репозитории, команды/запросы, DI-провайдер, роуты). Прикладные модули (`app/profiles`, `app/chats`, `app/notifications`) сознательно не документируются: они строятся по тем же правилам. При добавлении функционала копируйте паттерны из `app/auth`.

**Один код — четыре процесса** (см. `docker-compose.yaml`):

| Процесс | Entrypoint | Назначение |
|---|---|---|
| `app` | `app.main:init_app()` (gunicorn + uvicorn worker) | HTTP API и WebSocket-gateway |
| `consumers` | `app.consumers:app` (FastStream) | Потребление доменных событий из Kafka |
| `queue_worker` | `app.tasks:broker` (Taskiq) | Фоновые задачи |
| `scheduler` | `app.tasks:scheduler` (Taskiq) | Периодические задачи (в т.ч. очистка outbox) |

## Технологический стек

| Категория | Технологии |
|---|---|
| Web-фреймворк | [FastAPI](https://fastapi.tiangolo.com) 0.135+, Python 3.14, [uvicorn](https://www.uvicorn.org)/[gunicorn](https://gunicorn.org) |
| БД / ORM | [PostgreSQL](https://www.postgresql.org) 18 (`wal_level=logical`), [SQLAlchemy](https://www.sqlalchemy.org) 2.0 (async, asyncpg), [Alembic](https://github.com/sqlalchemy/alembic) |
| DI | [Dishka](https://github.com/reagento/dishka) |
| Кэш / Rate-limit | Redis (Valkey), `CacheRepository`, [fastapi-limiter](https://github.com/long2ice/fastapi-limiter) |
| Очереди задач | [Taskiq](https://taskiq-python.github.io) + taskiq-redis (worker + scheduler) |
| Message broker | Kafka: продюсер — [aiokafka](https://github.com/aio-libs/aiokafka), консьюмеры — [FastStream](https://faststream.ag2.ai) |
| Доставка событий | Transactional outbox + CDC: [Debezium](https://debezium.io) 2.7 (Kafka Connect) читает WAL Postgres и роутит `outbox_messages` в топики Kafka |
| Realtime | WebSocket-gateway поверх Redis Streams (`app/core/websocket`) |
| Хранилище файлов | [MinIO](https://min.io) (S3-совместимое), обработка медиа — pyvips / ffprobe |
| Почта | [aiosmtplib](https://aiosmtplib.readthedocs.io/en/stable) + Jinja2-шаблоны |
| Аутентификация | JWT ([pyjwt](https://pyjwt.readthedocs.io)), Argon2 ([argon2-cffi](https://argon2-cffi.readthedocs.io)), OAuth2 (Google, Yandex, GitHub), RBAC |
| Логирование | [structlog](https://www.structlog.org/en/stable) |
| Мониторинг | Prometheus, Grafana, Loki, Vector |
| Тесты | pytest, pytest-asyncio, [testcontainers](https://testcontainers-python.readthedocs.io) (Postgres, Redis) |
| Линтеры / типы | ruff, mypy, pylint, pre-commit |
| Инфраструктура | Docker / Docker Compose |

## Быстрый старт

```bash
git clone https://github.com/Forgot-0/fastapi_template.git
cd fastapi_template

# 1. Переменные окружения
cp .env.example .env
# отредактируйте .env: минимум SECRET_KEY, JWT_SECRET_KEY, POSTGRES_*, BROKER_URL

# 2. Docker-сеть (используется всеми docker-compose файлами проекта)
docker network create app-network

# 3. Поднять инфраструктуру и приложение
docker compose up --build

# Для прода
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml -f docker-compose.monitoring.yml up -d --build
```

`docker compose up` поднимает: `db` (Postgres с `infra/postgres/postgresql.conf`), `redis`, `kafka`, `minio`, `debezium` (Kafka Connect), одноразовый `debezium_connector` (регистрирует CDC-коннектор), одноразовый `migrations` (`alembic upgrade head` + `python -m app.init_data`), а затем `app`, `consumers`, `queue_worker` и `scheduler`.

После запуска:

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/api/v1/openapi.json> (доступен только в `local`/`testing` окружениях)
- Health-check: `GET /health`
- Метрики Prometheus: `GET /metrics` (у процесса `consumers` — на порту `9002`)
- Kafka Connect REST API: <http://localhost:8083>
- MinIO Console: <http://localhost:9001>

Проверить, что CDC-конвейер живой:

```bash
curl -s localhost:8083/connectors/outbox-connector/status
```

> Postgres обязан стартовать с `wal_level = logical` — иначе Debezium не создаст слот репликации и события останутся лежать в таблице `outbox_messages`. В compose это обеспечивает смонтированный `infra/postgres/postgresql.conf`.

### Линтинг и типы

```bash
poetry run ruff check .
poetry run mypy .
poetry run pylint app
pre-commit run --all-files
```

---

## Правила для AI-ассистентов

> Этот раздел — инструкция для LLM/AI-агентов (Claude, Copilot, Cursor и т.п.), которые будут писать код в этом репозитории. Следуйте ей так же строго, как и человек-разработчик.

1. **Не изобретайте новую архитектуру.** Проект уже задаёт паттерн: Router → Command/Query → Handler → Repository → Model. Любой новый функционал раскладывается по этим слоям, а не пишется «в одну функцию во вьюхе».
2. **Модуль `app/auth` — эталон.** Перед созданием нового модуля откройте соответствующие файлы `app/auth/*` и повторяйте структуру 1:1 (см. раздел [«Создание нового модуля»](#создание-нового-модуля)).
3. **DI только через Dishka.** Никаких глобальных синглтонов или `Depends()` с ручным созданием сервисов внутри роутера — сервисы и репозитории объявляются в `providers.py` и получаются через `FromDishka[...]`.
4. **Команды меняют состояние, запросы — только читают.** Используйте `BaseCommand`/`BaseCommandHandler` для записи и `BaseQuery`/`BaseQueryHandler` для чтения; не смешивайте побочные эффекты в query-хендлерах.
5. **Доменные события — только через outbox.** `event_bus.publish(model.pull_events())` вызывается **до** `session.commit()`, в той же транзакции. Прямой `broker.send_event(...)`/`send_data(...)` из команды для доменных событий запрещён — см. [Событийная архитектура](#событийная-архитектура-outbox--wal--debezium).
6. **Реакция на событие — это FastStream-подписчик**, а не in-process обработчик. Подписчик обязан быть идемпотентным через `EventIdempotencyGuard`, а его топик и `group_id` — лежать в `config.py` модуля.
7. **Фильтрация и пагинация — через `app.core.filters`.** Не пишите вручную `WHERE`/`LIMIT/OFFSET` в репозиториях — создавайте `XxxFilter(BaseFilter)` и используйте `find_by_filter`.
8. **Доступ — через зависимости и RBAC-менеджер.** Аутентификация — аннотациями из `app/auth/deps.py`; проверка прав — `rbac_manager.check_permission(...)` первой строкой хендлера или отдельной FastAPI-зависимостью. Никаких `if user.role == ...` внутри бизнес-логики.
9. **Модели наследуют `BaseModel` (+ миксины).** Новая модель обязательно регистрируется в `app/core/models.py`, иначе Alembic её не увидит.
10. **Придерживайтесь соглашений по именованию** из раздела [«Соглашения по именованию»](#3-соглашения-по-именованию) (`CreateArticle`, `GetListArticles`, `ArticleFilter`, `ArticleRepository`, событие `module.entity.action`).
11. **Каждое изменение бизнес-логики сопровождается тестом** в `tests/` (unit — без БД/Docker, integration — с `testcontainers`, по аналогии с `tests/auth`).
12. **Код обязан проходить `ruff`, `mypy` и `pylint`** — используйте существующие конфиги (`.ruff.toml`, `mypy.ini`, `.pylintrc`), не отключайте правила без крайней необходимости.
13. **Не добавляйте новые зависимости/сервисы «по умолчанию».** Если задачу можно решить существующими (`CacheRepository`, `QueueService`, `StorageService`, `BaseMailService`, `BaseMessageBroker`, `IdempotencyStore`) — используйте их, а не новую библиотеку.
14. **Секреты и конфигурация — только через `.env` / `BaseConfig`.** Не хардкодьте ключи, хосты, пароли, имена топиков и `group_id` в коде.

---

## Содержание

- [FastAPI Template](#fastapi-template)
  - [Технологический стек](#технологический-стек)
  - [Быстрый старт](#быстрый-старт)
    - [Линтинг и типы](#линтинг-и-типы)
  - [Правила для AI-ассистентов](#правила-для-ai-ассистентов)
  - [Содержание](#содержание)
  - [Введение](#введение)
    - [Project Structure](#project-structure)
    - [Database Layer](#database-layer)
    - [API Layer](#api-layer)
    - [Config](#config)
    - [Dependency Injection](#dependency-injection)
  - [Security](#security)
    - [Аутентификация в роутере](#аутентификация-в-роутере)
    - [RBAC внутри Query/Command-хендлеров](#rbac-внутри-querycommand-хендлеров)
    - [OAuth Authentication](#oauth-authentication)
  - [Filter System](#filter-system)
  - [Событийная архитектура: Outbox + WAL + Debezium](#событийная-архитектура-outbox--wal--debezium)
    - [Поток события](#поток-события)
    - [Что попадает в outbox\_messages](#4-что-попадает-в-outbox_messages)
    - [Postgres WAL → Debezium](#5-postgres-wal--debezium)
    - [Kafka → FastStream consumer](#6-kafka--faststream-consumer)
    - [Идемпотентность](#7-идемпотентность)
    - [Очистка outbox](#8-очистка-outbox)
    - [Гарантии и следствия](#гарантии-и-следствия)
    - [Чек-лист нового события](#чек-лист-нового-события)
  - [Core Services](#core-services)
    - [Кэширование (CacheRepository)](#кэширование-cacherepository)
    - [Queue Service](#queue-service)
    - [Mail Service](#mail-service)
    - [Storage Service](#storage-service)
    - [WebSocket Service](#websocket-service)
    - [Message Brokers](#message-brokers)
    - [Logging Service](#logging-service)
    - [Monitoring](#monitoring)
    - [Middleware](#middleware)
  - [Application Lifecycle](#application-lifecycle)
    - [Процесс app (HTTP + WebSocket)](#процесс-app-http--websocket)
    - [Процесс consumers (FastStream)](#процесс-consumers-faststream)
    - [Процессы queue\_worker и scheduler (Taskiq)](#процессы-queue_worker-и-scheduler-taskiq)
    - [Миграции и первичные данные](#миграции-и-первичные-данные)
  - [Создание нового модуля](#создание-нового-модуля)
    - [1. Структура модуля](#1-структура-модуля)
    - [2. Пошаговое создание](#2-пошаговое-создание)
    - [3. Соглашения по именованию](#3-соглашения-по-именованию)

---

## Введение

### Project Structure

```
social_github/
├── migrations/          # Alembic migrations
├── infra/
│   ├── debezium/outbox-connector.json   # Конфиг CDC-коннектора (регистрируется автоматически)
│   ├── postgres/postgresql.conf         # wal_level=logical, слоты репликации
│   └── livekit/
├── monitoring/          # Grafana / Loki / Vector / Prometheus
├── nginx/               # Reverse-proxy конфиги
├── loadtests/           # Нагрузочные сценарии
├── tests/               # unit + integration (testcontainers)
├── app/
│   ├── main.py          # Entrypoint FastAPI (HTTP + WebSocket)
│   ├── consumers.py     # Entrypoint FastStream (потребление Kafka)
│   ├── tasks.py         # Entrypoint Taskiq (worker + scheduler)
│   ├── pre_start.py     # Retry-проверка доступности БД
│   ├── init_data.py     # Первичные данные (роли)
│   ├── core/            # Инфраструктура
│   │   ├── api/         # builder, rate_limiter, schemas, filter_mapper, utils
│   │   ├── commands.py  # BaseCommand / BaseCommandHandler
│   │   ├── queries.py   # BaseQuery / BaseQueryHandler
│   │   ├── configs/     # AppConfig, BaseConfig, SMTP-конфиг
│   │   ├── consumers/   # DTO входящих событий + EventIdempotencyGuard
│   │   ├── db/          # base_model, repository (+CacheRepository), session, convertor
│   │   ├── di/          # Dishka-контейнер и инфраструктурные провайдеры
│   │   ├── events/      # BaseEvent, EventRegistry, BaseEventBus, MediatorEventBus
│   │   ├── outbox/      # model, repository, serializer, task (очистка), metrics
│   │   ├── filters/     # base, condition, sort, pagination, loading_strategy
│   │   ├── log/         # structlog
│   │   ├── mediators/   # Реестры команд и запросов
│   │   ├── message_brokers/  # BaseMessageBroker + KafkaMessageBroker
│   │   ├── middlewares/      # ContextMiddleware, LoggingMiddleware
│   │   ├── services/    # auth (JWT, RBAC-порт), mail, media, queues, storage, idempotency
│   │   ├── websocket/   # WS-gateway: manager, presence, keys, dtos
│   │   ├── metrics.py   # Prometheus-метрики WS и доставки
│   │   ├── models.py    # Центральный импорт всех ORM-моделей (для Alembic)
│   │   ├── routers.py   # /health
│   │   ├── tasks.py     # register_tasks(broker) — сборка всех Taskiq-задач
│   │   └── exceptions.py     # ApplicationError и базовые ошибки
│   └── auth/            # Reference-модуль
│       ├── commands/    # Command + Handler (auth, permissions, roles, sessions, users)
│       ├── consumers/   # FastStream-подписчики на топик auth
│       ├── queries/     # Query + Handler
│       ├── dtos/        # Внутренние DTO (UserDTO, AuthUserJWTData, …)
│       ├── schemas/     # Pydantic request / response схемы
│       ├── filters/     # UserFilter, RoleFilter, …
│       ├── models/      # User, Role, Permission, Session, OAuthAccount (+ доменные события)
│       ├── repositories/  # Data access (SQLAlchemy + Redis)
│       ├── routes/v1/   # auth, user, roles, permissions, sessions
│       ├── services/    # jwt, hash, session, cookie_manager, device, rbac, oauth_*
│       ├── events/      # Обработчики доменных событий модуля
│       ├── emails/      # Шаблоны писем и HTML-вьюхи
│       ├── config.py    # AuthConfig (JWT TTL, OAuth, USER_TOPIC)
│       ├── deps.py      # CurrentUserModel, ActiveUserModel, AuthCurrentUserJWTData
│       ├── exceptions.py
│       ├── providers.py # Dishka DI-провайдер модуля
│       ├── routers.py   # Агрегирующий роутер v1
│       └── tasks.py     # register_auth_tasks(broker)
├── docker-compose.yaml  # app, consumers, queue_worker, scheduler, migrations,
│                        # db, redis, kafka, debezium, debezium_connector, minio
└── pyproject.toml
```

> Прикладные модули (`app/profiles`, `app/chats`, `app/notifications`) в дереве опущены сознательно — они повторяют структуру `app/auth` и в этом README не описываются.

---

### Database Layer

**Используется:**

- Database: [PostgreSQL](https://www.postgresql.org)
- Async adapter: [asyncpg](https://pypi.org/project/asyncpg/)
- ORM: [SQLAlchemy](https://www.sqlalchemy.org) 2.0+ (async)
- Migrations: [Alembic](https://github.com/sqlalchemy/alembic)

**Key Notes:**

- `app.core.db.base_model.BaseModel` — базовый класс для всех моделей, наследует `sqlalchemy.orm.DeclarativeBase`. Держит буфер доменных событий: `register_event()` / `pull_events()` (см. [Событийная архитектура](#событийная-архитектура-outbox--wal--debezium)).
- `app.core.db.base_model.DateMixin` — добавляет поля `created_at` и `updated_at`.
- `app.core.db.base_model.SoftDeleteMixin` — «мягкое» удаление через поле `deleted_at`. Предоставляет `select_not_deleted()` classmethod и `soft_delete()` / `is_deleted()`.
- Все модели должны быть импортированы в `app/core/models.py`, чтобы Alembic их видел.
- Репозитории наследуют `IRepository[Model]` (`app/core/db/repository.py`); чтение списков идёт через `find_by_filter(model, filters)` → `PageResult[Model]`.

```python
from app.core.db.base_model import BaseModel, DateMixin, SoftDeleteMixin

class Post(BaseModel, DateMixin, SoftDeleteMixin):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
```

---

### API Layer

**Используется:**

- Rate limiting: [fastapi-limiter](https://github.com/long2ice/fastapi-limiter) + Redis
- Metrics: [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator)

**Структура эндпоинтов и схем**

Каждый модуль организован следующим образом:

- `routes/v<N>/<entity>.py` — роутеры FastAPI
- `schemas/<entity>/requests.py` — входящие Pydantic-схемы с методом `to_<entity>_filter() -> Filter`
- `schemas/<entity>/responses.py` — исходящие схемы

Пример схемы запроса со встроенной конвертацией в фильтр:

```python
class GetUsersRequest(BaseModel):
    email: str | None = None
    is_active: bool | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    sort: str | None = Field(default=None, examples=["created_at:desc,username:asc"])

    def to_user_filter(self) -> UserFilter:
        user_filter = UserFilter(email=self.email, is_active=self.is_active)
        user_filter.set_pagination(Pagination(page=self.page, page_size=self.page_size))
        for sf in FilterMapper.parse_sort_string(self.sort):
            user_filter.add_sort(sf.field, sf.direction)
        return user_filter
```

Использование в роутере:

```python
@router.get("/")
async def get_list(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: AuthCurrentUserJWTData,
    params: Annotated[GetUsersRequest, Query()],
) -> PageResult[UserDTO]:
    return await mediator.handle_query(
        GetListUserQuery(user_jwt_data=user_jwt_data, user_filter=params.to_user_filter())
    )
```

**Rate Limiter**

`app.core.api.rate_limiter.ConfigurableRateLimiter` — обёртка над `RateLimiter` из `fastapi-limiter`:

```python
from app.core.api.rate_limiter import ConfigurableRateLimiter

router = APIRouter(dependencies=[Depends(ConfigurableRateLimiter(times=3, seconds=60))])

# или на конкретном эндпоинте:
@app.get("/", dependencies=[Depends(ConfigurableRateLimiter(times=3, seconds=60))])
async def index(): ...
```

**Формирование ответов об ошибках**

`app.core.api.builder.create_response` генерирует OpenAPI-совместимое описание ошибки:

```python
@router.post(
    "/login",
    responses={400: create_response(WrongLoginDataError(username="user"))}
)
async def login(...): ...
```

---

### Config

**Key Notes:**

- Глобальный конфиг: `app.core.configs.app.app_config` (класс `AppConfig`).
- Каждый модуль может иметь собственный `config.py`, унаследованный от `app.core.configs.base.BaseConfig` (в нём же — имена Kafka-топиков и `group_id` подписчиков модуля).
- Все настройки читаются из файла `.env`.
- `.env.example` — шаблон всех переменных; скопируйте его в `.env` при первом развёртывании.

---

### Dependency Injection

Используется фреймворк [Dishka](https://github.com/reagento/dishka).

**Container Setup** (`app/core/di/container.py`) — единый контейнер для всех процессов:

```python
from dishka import AsyncContainer, Provider, make_async_container

from app.auth.providers import AuthModuleProvider
from app.core.di import get_core_providers


def create_container(*app_providers: Provider) -> AsyncContainer:
    providers = [
        *get_core_providers(),   # инфраструктура app/core
        AuthModuleProvider(),    # провайдеры модулей
        # ...
    ]
    return make_async_container(*providers, *app_providers)
```

`get_core_providers()` (`app/core/di/__init__.py`) собирает инфраструктурные провайдеры: `BrokerProvider`, `DBProvider` (engine/sessionmaker/`AsyncSession`/`OutboxRepository`/`Redis`), `CoreProvider` (MinIO, media-probe, `IdempotencyStore`), `MediatorProvider`, `EventProvider` (`EventRegistry`, `BaseEventBus`, `EventIdempotencyGuard`), `QueueProvider`, `MailProvider`, `AuthServicesProvider`, `CoreWSProvider`.

Аргумент `*app_providers` — это интеграция конкретного процесса, поэтому один и тот же контейнер работает везде:

```python
create_container()                        # FastAPI (app/main.py)
create_container(FastStreamProvider())    # consumers (app/consumers.py)
create_container(TaskiqProvider())        # worker / scheduler (app/tasks.py)
```

**Инициализация с FastAPI:**

```python
from dishka.integrations.fastapi import setup_dishka
from app.core.di.container import create_container

app = FastAPI(lifespan=lifespan)
container = create_container()
setup_dishka(container=container, app=app)
```

**Использование в эндпоинтах** (роутер должен быть создан с `route_class=DishkaRoute`):

```python
from dishka import FromDishka
from app.core.mediators.base import BaseMediator

@router.get("/")
async def example(mediator: FromDishka[BaseMediator]):
    return await mediator.handle_query(SomeQuery(...))
```

В подписчиках FastStream и задачах Taskiq — тот же `FromDishka`, но с `@inject` из соответствующей интеграции (`dishka.integrations.faststream` / `dishka.integrations.taskiq`).

**Lifetime scopes:** `APP` — инфраструктура на весь процесс (брокер, Redis, MinIO, менеджеры); `REQUEST` — всё, что живёт в рамках запроса/сообщения (`AsyncSession`, репозитории, хендлеры, `BaseEventBus`).

---

## Security

### Аутентификация в роутере

Текущий пользователь приезжает в эндпоинт FastAPI-зависимостью, а не достаётся вручную из заголовков. Готовые аннотации — в `app/auth/deps.py`:

| Аннотация | Что даёт | Стоимость |
|---|---|---|
| `AuthCurrentUserJWTData` | `AuthUserJWTData` — данные из подписанного JWT (id, roles, permissions) | Без похода в БД |
| `CurrentUserModel` | `UserDTO` — пользователь, загруженный по access-токену | Запрос в БД |
| `ActiveUserModel` | То же + проверка `is_active` | Запрос в БД |

```python
@router.get("/")
async def get_list(
    mediator: FromDishka[BaseMediator],
    user_jwt_data: AuthCurrentUserJWTData,
) -> PageResult[UserDTO]: ...
```

Базовый вариант без зависимости от модуля `auth` — `CurrentUserJWTData` из `app/core/services/auth/depends.py` (`UserJWTDataGetter` + `HTTPBearer`): он знает только про `UserJWTData` и используется кодом, который не должен импортировать `app/auth`.

**Проверку прав** оформляйте либо отдельной функцией-зависимостью, либо через RBAC-менеджер внутри хендлера (см. следующий раздел). Функция-зависимость подходит, когда решение не зависит от тела запроса:

```python
# app/<module>/deps.py
async def can_update(user: AuthCurrentUserJWTData, rbac: FromDishka[RBACManagerInterface]) -> None:
    if not rbac.check_permission(user, {"post:update"}):
        raise AccessDeniedError(need_permissions={"post:update"})


@router.patch("/{post_id}", dependencies=[Depends(can_update)])
async def update(post_id: int) -> None: ...
```

Чего делать не нужно — писать `if user.role == "admin"` внутри бизнес-логики: решение о доступе принимает RBAC-менеджер, а исключение `AccessDeniedError` глобальный exception-хендлер сам превращает в HTTP 403.

### RBAC внутри Query/Command-хендлеров

Зависимости из раздела выше проверяют права ещё до входа в хендлер (на уровне FastAPI-зависимости). Но там, где решение о доступе зависит от данных самого запроса (например, `AuthUserJWTData` уже приехал внутрь `Query`/`Command`, а не отдельным параметром роута), проверку делают прямо в `handle()` через RBAC-менеджер — как в [`GetListUserQueryHandler`](#2-пошаговое-создание).

**Порт и адаптер, а не два независимых менеджера.** Это модульный монолит: модуль `app/auth` может быть в будущем полностью удалён и заменён, например, клиентом к внешнему auth-микросервису. Чтобы core и другие модули не зависели от того, как именно `app/auth` считает роли/права, RBAC оформлен как классический port/adapter (инверсия зависимостей):

- **`app.core.services.auth.rbac.RBACManagerInterface`** (core) — абстрактный контракт (`ABC`), знает только про базовый `UserJWTData`. Core и любой другой модуль зависят **только** от этого интерфейса (`FromDishka[RBACManagerInterface]`) и никогда не импортируют `app.auth` напрямую.
- **`app.auth.services.rbac.AuthRBACManager`** (модуль `app/auth`) — конкретная реализация (`AuthRBACManager(RBACManagerInterface)`), которая уже знает про `RolesEnum`/`PermissionEnum` и добавляет модуль-специфичные проверки.
- Связывает их DI: `AuthModuleProvider` регистрирует `AuthRBACManager` как обычный сервис и дополнительно объявляет `alias(source=AuthRBACManager, provides=RBACManagerInterface)` — тот же singleton доступен под двумя типами. Замена auth-модуля на внешний сервис = замена одного `alias`/провайдера в одном месте, без единой правки в core или в других модулях.

| | `RBACManagerInterface` (порт, `app/core`) | `AuthRBACManager` (адаптер, `app/auth`) |
|---|---|---|
| Роль | Контракт: что core вправе ожидать от RBAC, не зная деталей | Единственная реализация контракта сейчас |
| `check_permission(jwt_data, perms)` | Абстрактный метод контракта | `True`, если пользователь — системная роль (`RolesEnum.SYSTEM_ADMIN`/`SUPER_ADMIN`) либо обладает всеми `perms`; пустой `perms` — всегда `True` |
| `is_system_user(jwt_data)` | Абстрактный метод контракта | Роли берутся из `RolesEnum`, а не хардкодятся строками |
| `validate_role_name(jwt_data, name)` | — (не часть общего контракта, модуль-специфично) | Проверяет длину имени роли (3–24 символа) и что системные префиксы (`system_`, `admin_`) создают только системные пользователи |
| `validate_permissions(jwt_data, perm)` | — | Запрещает выдавать/редактировать `protected_permissions` (например, `MANAGE_SYSTEM_SETTINGS`, `ASSIGN_ROLE`) не-системным пользователям |
| `check_security_level(user_level, role_level)` | — | Запрещает управлять ролью с уровнем ≥ уровня самого пользователя (иерархия ролей) |

Модуль-специфичные методы (`validate_role_name`, `validate_permissions`, `check_security_level`) сознательно не вынесены в `RBACManagerInterface` — это детали конкретно ролевой модели `app/auth` (иерархия уровней, защищённые permissions), а не то, что обязано знать/предоставлять любое совместимое хранилище прав. В интерфейс попадает только тот минимум, которым реально пользуется код за пределами `app/auth`.

`AccessDeniedError(need_permissions=...)` (`app.core.services.auth.exceptions`) — единый формат ошибки для всего проекта, конвертируется глобальным exception-хендлером в HTTP 403 с телом `{"code": "ACCESS_DENIED", "detail": {"permissions": [...]}}`.

**Правило:** если хендлеру нужна и пагинация/кэш, и RBAC — проверка прав всегда идёт первой инструкцией в `handle()`, до вызова `cache_paginated`/`cache` (см. объяснение в разборе `GetListUserQueryHandler`).

### OAuth Authentication

**Поддерживаемые провайдеры:** Google, Yandex, GitHub (`app/auth/services/oauth_providers.py`).

**Структура:**

- `OAuthProvider` — абстрактный базовый класс (`OAuthGoogle`, `OAuthYandex`, `OAuthGithub`)
- `OAuthProviderFactory` — реестр провайдеров, создаётся в `AuthModuleProvider`
- `OAuthManager` — фасад для получения URL авторизации и обработки callback
- `OAuthAccount` — ORM-модель привязки внешнего аккаунта к `User`

**API Endpoints** (приложение поднято с `redirect_slashes=False`, поэтому завершающий слэш обязателен):

| Method | Path | Описание |
|--------|------|----------|
| `GET` | `/api/v1/auth/oauth/{provider}/authorize/` | Получить URL авторизации |
| `GET` | `/api/v1/auth/oauth/{provider}/authorize/connect/` | Привязать OAuth к существующему аккаунту (требует авторизации) |
| `GET` | `/api/v1/auth/oauth/{provider}/callback/` | Callback от провайдера, возвращает `AccessTokenResponse` и ставит refresh-cookie |

**Конфигурация** (`.env`, класс `AuthConfig` в `app/auth/config.py`):

```env
OAUTH_GOOGLE_CLIENT_ID=...
OAUTH_GOOGLE_CLIENT_SECRET=...
OAUTH_GOOGLE_REDIRECT_URI=https://api.example.com/api/v1/auth/oauth/google/callback
# Аналогично для YANDEX и GITHUB
```

URL авторизации / обмена токена / userinfo для каждого провайдера тоже вынесены в конфиг (`OAUTH_<PROVIDER>_BASE_AUTH_URL`, `..._TOKEN_URL`, `..._USERINFO_URL`) — переопределяются через `.env` без правки кода.

---

## Filter System

Система фильтрации реализована в `app/core/filters/` и обеспечивает типобезопасное построение SQL-запросов через `SQLAlchemyFilterConverter`.

**Компоненты:**

- `BaseFilter` — базовый класс фильтра; хранит условия, сортировку, пагинацию и стратегии загрузки связей.
- `FilterCondition` / `FilterOperator` — одно условие фильтра и доступные операторы.
- `Pagination` — параметры страницы (page, page_size, offset, limit).
- `SortField` / `SortDirection` — параметры сортировки.
- `RelationshipLoading` / `LoadingStrategyType` — стратегии загрузки связей (`LAZY`, `JOINED`, `SELECTIN`, `SUBQUERY`, `IMMEDIATE`).

**Создание фильтра:**

```python
from dataclasses import dataclass
from app.core.filters.base import BaseFilter
from app.core.filters.condition import FilterOperator
from app.core.filters.loading_strategy import LoadingStrategyType

@dataclass
class PostFilter(BaseFilter):
    title: str | None = None
    is_published: bool | None = None

    def build_condition(self) -> None:
        self.add_condition("title", FilterOperator.CONTAINS, self.title)
        self.add_condition("is_published", FilterOperator.EQ, self.is_published)
        self.add_relation("author", LoadingStrategyType.SELECTIN)
```

**Использование в репозитории:**

```python
# IRepository.find_by_filter() применяет фильтр автоматически
result: PageResult[Post] = await self.post_repository.find_by_filter(
    model=Post,
    filters=PostFilter(title="fastapi", is_published=True)
)
```

**Доступные операторы** (`FilterOperator`):

`EQ`, `NE`, `GT`, `GTE`, `LT`, `LTE`, `IN`, `NOT_IN`, `LIKE`, `ILIKE`, `CONTAINS`, `ALL`, `ANY`, `STARTS_WITH`, `ENDS_WITH`, `IS_NULL`, `IS_NOT_NULL`, `IS_NULL_FROM`, `IS_NOT_NULL_FROM`

**Пагинация и сортировка:**

```python
from app.core.filters.pagination import Pagination
from app.core.filters.sort import SortDirection
from app.core.api.filter_mapper import FilterMapper

post_filter = PostFilter(title="fastapi")
post_filter.set_pagination(Pagination(page=1, page_size=20))
post_filter.add_sort("created_at", SortDirection.DESC)

# Парсинг строки сортировки из query-параметров:
for sf in FilterMapper.parse_sort_string("created_at:desc,title:asc"):
    post_filter.add_sort(sf.field, sf.direction)
```

**`PageResult`** — возвращаемый тип `find_by_filter`:

```python
@dataclass(frozen=True)
class PageResult[T]:
    items: list[T]
    total: int
    page: int
    page_size: int
    # computed: total_pages, has_next, has_previous, next_page, previous_page
```

---

## Событийная архитектура: Outbox + WAL + Debezium

Доменные события **никогда не отправляются в Kafka напрямую из кода приложения**. Используется связка *transactional outbox* + *change data capture (CDC)*: команда записывает событие в таблицу `outbox_messages` в **той же транзакции**, что и бизнес-данные, а доставку в Kafka берёт на себя Debezium, читающий WAL PostgreSQL.

Это даёт то, чего нельзя добиться прямым `producer.send()` внутри хендлера: либо коммитятся и данные, и событие, либо ни то, ни другое. Событие не теряется, если процесс упал сразу после коммита, и не появляется, если транзакция откатилась.

### Поток события

```
┌────────────────────────── app (FastAPI) ───────────────────────────┐
│  CommandHandler                                                    │
│    model.register_event(SomeEvent(...))   ← событие в модели       │
│    repository.create(model)                                        │
│    event_bus.publish(model.pull_events()) ← INSERT в outbox        │
│    session.commit()                       ← одна транзакция        │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │ outbox_messages
                                   ▼
                 ┌───────────────────────────────┐
                 │         PostgreSQL WAL        │
                 │  wal_level = logical          │
                 │  slot:        outbox_slot     │
                 │  publication: social_outbox   │
                 └───────────────┬───────────────┘
                                 │ logical replication (pgoutput)
                                 ▼
                 ┌───────────────────────────────┐
                 │    Debezium (Kafka Connect)   │
                 │  PostgresConnector            │
                 │  + EventRouter SMT (outbox)   │
                 └───────────────┬───────────────┘
                                 │ topic = колонка `topic`
                                 │ key   = колонка `aggregate_id`
                                 ▼
                 ┌───────────────────────────────┐
                 │             Kafka             │
                 │  топики: auth, profiles, …    │
                 └───────────────┬───────────────┘
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │     consumers (FastStream)    │
                 │  @router.subscriber(topic, …) │
                 │  EventIdempotencyGuard        │
                 │  mediator.handle_command(...) │
                 └───────────────────────────────┘
```

### 1. Событие объявляется рядом с моделью

```python
# app/auth/models/user.py
@dataclass(frozen=True)
class CreatedUserEvent(BaseEvent):
    email: str
    username: str

    __event_name__: str = "auth.user.created"

    def get_partition_key(self) -> str:
        return str(self.username)
```

- `__event_name__` обязателен и состоит **минимум из трёх сегментов**: `<модуль>.<агрегат>.<действие>` в прошедшем времени. Из него выводятся и топик, и `aggregate_type` — см. шаг 3.
- `get_partition_key()` обязателен (абстрактный метод `BaseEvent`) — его значение становится ключом Kafka-сообщения, то есть определяет партицию и, следовательно, **порядок событий в пределах одного агрегата**.
- `event_id` (uuid4) и `created_at` проставляются автоматически, событие неизменяемо (`frozen=True`).

### 2. Модель регистрирует событие

`BaseModel` (`app/core/db/base_model.py`) хранит буфер событий: `register_event()` кладёт событие, `pull_events()` забирает и очищает буфер.

```python
class User(BaseModel, DateMixin, SoftDeleteMixin):
    @classmethod
    def create(cls, ...) -> "User":
        user = cls(...)
        user.register_event(CreatedUserEvent(email=user.email, username=user.username))
        return user
```

### 3. Команда публикует события в той же транзакции

```python
# app/auth/commands/users/register.py
user = User.create(...)
await self.user_repository.create(user)

await self.event_bus.publish(user.pull_events())   # INSERT в outbox_messages
await self.session.commit()                        # один коммит на данные + события
await self.user_repository.invalidate_cache()
```

`MediatorEventBus` (`app/core/events/mediator/service.py`) не ходит в Kafka — он только пишет строки в outbox через `OutboxRepository` (тот же `AsyncSession`, `Scope.REQUEST`) и инкрементирует счётчик `outbox_events_written_total{topic,event_name}`.

**`publish()` обязан вызываться до `commit()`.** После коммита `session.add()` не попадёт в ту же транзакцию, и вся гарантия теряется.

### 4. Что попадает в `outbox_messages`

`OutboxMessage.create()` раскладывает событие по колонкам:

| Колонка | Значение | Пример для `auth.user.created` |
|---|---|---|
| `id` | `uuid7` (монотонный — сохраняет порядок вставки) | `0192...` |
| `topic` | `event_name.split(".", 1)[0]` | `auth` |
| `aggregate_type` | `event_name.split(".")[1]` | `user` |
| `aggregate_id` | `event.get_partition_key()` | `john` |
| `event_name` | `__event_name__` | `auth.user.created` |
| `payload` | `JSONB` — поля события без `event_id`/`created_at` | `{"email": ..., "username": ...}` |
| `headers` | `JSONB` — по умолчанию `{}` | `{}` |
| `created_at` / `updated_at` | `DateMixin` | |

Сериализация — `app/core/outbox/serializer.py`: `asdict(event)` + `json.dumps(..., default=additionally_serialize)`, поэтому в payload попадают только JSON-совместимые значения (UUID/datetime/Enum приводятся к строкам).

> Топик выводится из имени события, а не задаётся вручную. Все события модуля `auth` уезжают в топик `auth`, `profiles.*` — в `profiles` и т.д. Из-за этого имя события **обязано** содержать хотя бы три сегмента: `event_name.split(".")[1]` иначе упадёт.

### 5. Postgres WAL → Debezium

`infra/postgres/postgresql.conf`:

```conf
wal_level = logical
max_replication_slots = 10
max_wal_senders = 10
```

`infra/debezium/outbox-connector.json` — коннектор регистрируется автоматически контейнером `debezium_connector` (POST в Kafka Connect REST API на `:8083`, идемпотентно — если коннектор уже есть, повтор пропускается). Ключевые параметры:

| Параметр | Значение | Зачем |
|---|---|---|
| `plugin.name` | `pgoutput` | Встроенный в Postgres logical decoding, без внешних расширений |
| `slot.name` / `publication.name` | `outbox_slot` / `social_outbox` | Слот репликации и публикация; `publication.autocreate.mode=filtered` создаёт публикацию только на нужную таблицу |
| `table.include.list` | `public.outbox_messages` | CDC читает **только** outbox, а не все таблицы |
| `snapshot.mode` | `no_data` | При первом старте не переигрывать историю — берём только новые записи |
| `tombstones.on.delete` | `false` | Удаление строк задачей очистки не порождает tombstone-сообщений в топиках |
| `heartbeat.interval.ms` | `10000` | Heartbeat двигает слот, даже когда в outbox тихо, а в БД идёт другая запись |

`EventRouter`-SMT (`io.debezium.transforms.outbox.EventRouter`) превращает CDC-строку в доменное сообщение:

```
transforms.outbox.table.field.event.id       = id
transforms.outbox.table.field.event.key      = aggregate_id   → key Kafka-сообщения
transforms.outbox.table.field.event.type     = event_name
transforms.outbox.table.field.event.payload  = payload        (expand.json.payload = true)
transforms.outbox.route.by.field             = topic          → имя топика берётся из колонки
transforms.outbox.table.fields.additional.placement =
    id:envelope:event_id, event_name:envelope:event_name,
    created_at:envelope:created_at, event_name:header:event_name
```

На выходе в Kafka:

```json
// key: "john"      headers: { "event_name": "auth.user.created" }
{
  "event_id": "0192f0c4-...",
  "event_name": "auth.user.created",
  "created_at": "2026-09-06T10:15:00Z",
  "payload": { "email": "john@example.com", "username": "john" }
}
```

Этот формат один в один описан DTO в `app/core/consumers/event.py` — `DictEventDTO` (нетипизированный payload) и `TypedEventDTO[PayloadT]` (payload валидируется Pydantic-моделью).

### 6. Kafka → FastStream consumer

Реакция на событие — это **подписчик в процессе `consumers`**, а не обработчик внутри процесса `app`:

```python
# app/<module>/consumers/<name>.py
router = KafkaRouter()

@router.subscriber(module_config.SOME_TOPIC, group_id=module_config.SOME_GROUP_ID)
@inject
async def handle(
    event: TypedEventDTO[SomePayload],
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if not await idempotency_guard.try_acquire(group=module_config.SOME_GROUP_ID, event_id=event.event_id):
        return
    try:
        await mediator.handle_command(SomeCommand(...))
    except Exception:
        await idempotency_guard.release(group=module_config.SOME_GROUP_ID, event_id=event.event_id)
        raise
```

Роутер подключается в `setup_router()` в `app/consumers.py`.

В топик приходят **все** события модуля-издателя, поэтому подписчик обязан отсеять чужие. Два рабочих способа:

```python
# 1. Ветвление внутри обработчика (DictEventDTO) — как в app/auth/consumers/user.py.
#    Подходит, когда в топике заведомо есть события других типов:
#    сообщение просто игнорируется, без ошибок в логах.
if event.event_name != CreatedUserEvent.get_name():
    return

# 2. Фильтр подписчика — как в app/chats/consumers/profiles.py.
@subscriber(filter=lambda msg: msg.headers.get("event_name") in SOME_EVENT_NAMES)
```

У фильтра есть цена: сообщение, не подошедшее ни под один фильтр, FastStream логирует как `SubscriberNotFound` (уровень ERROR) и пропускает. Если в топике постоянно есть события мимо фильтра — берите первый вариант.

**Живой пример.** `app/auth/consumers/user.py` слушает топик `auth` в группе `send-verify-email`, отбирает `auth.user.created`, проверяет идемпотентность и вызывает `SendVerifyEventHandler` — так после регистрации пользователю уходит письмо с кодом подтверждения.

### 7. Идемпотентность

CDC даёт **at-least-once**: после рестарта Debezium или ребаланса consumer-группы сообщение может прийти повторно. Поэтому каждый подписчик проходит через `EventIdempotencyGuard` (`app/core/consumers/idempotency.py`) — `SET consumers:processed:{group}:{event_id} 1 EX 7d NX` в Redis:

- ключ уже есть → событие уже обработано этой группой, выходим;
- обработка упала → `release()`, чтобы повторная доставка не была проглочена.

Ключ включает `group`, поэтому одно и то же событие может независимо обработаться разными consumer-группами.

Для идемпотентности **входящих HTTP-запросов** есть отдельный `IdempotencyStore` (`app/core/services/idempotency.py`) — он кэширует результат операции по клиентскому ключу и берёт лок на время выполнения.

### 8. Очистка outbox

Таблица растёт бесконечно, поэтому `OutboxCleanupTask` (`app/core/outbox/task.py`) — периодическая Taskiq-задача в процессе `scheduler`/`queue_worker` — удаляет строки старше `OUTBOX_RETENTION_DAYS` батчами по `OUTBOX_CLEANUP_BATCH_SIZE` (не более `MAX_CLEANUP_BATCHES_PER_RUN = 50` батчей за запуск), считая `outbox_cleanup_deleted_total`.

Удаление безопасно: EventRouter публикует только `INSERT`-события, а `tombstones.on.delete=false` не даёт появиться tombstone-записям. Ретенция должна быть заметно больше максимально ожидаемого лага Debezium.

### Гарантии и следствия

| | Что даёт | Что нужно помнить |
|---|---|---|
| Атомарность | Событие и данные коммитятся вместе | `publish()` — строго до `commit()` |
| Доставка | At-least-once | Каждый подписчик обязан быть идемпотентным |
| Порядок | В пределах партиции, то есть в пределах `get_partition_key()` | Между разными агрегатами порядок не гарантирован |
| Связность модулей | Модули не импортируют друг друга, общаются через топики | Payload — это публичный контракт: поля можно добавлять, но не переименовывать/удалять |
| Слот репликации | Debezium не теряет позицию при рестарте | Если `consumers`/Debezium долго лежат, **WAL накапливается на диске БД** — мониторьте лаг слота |

### Настройки

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `OUTBOX_RETENTION_DAYS` | `7` | Сколько дней хранить отправленные строки |
| `OUTBOX_CLEANUP_INTERVAL_SECONDS` | `3600` | Период запуска задачи очистки (переводится в cron-выражение) |
| `OUTBOX_CLEANUP_BATCH_SIZE` | `5000` | Размер батча `DELETE ... RETURNING` |
| `BROKER_URL` | — | `bootstrap.servers` Kafka |
| `GROUP_ID` | — | `client_id` продюсера/консьюмера по умолчанию |

Имена топиков и `group_id` подписчиков объявляются в `config.py` модуля (`BaseConfig`), а не хардкодятся в коде подписчика.

### Метрики

| Метрика | Где | Смысл |
|---|---|---|
| `outbox_events_written_total{topic,event_name}` | `app` | Сколько событий записано в outbox |
| `outbox_cleanup_deleted_total` | `scheduler` | Сколько строк удалено ретенцией |

Лаг и состояние коннектора смотрятся через Kafka Connect REST API:

```bash
curl -s localhost:8083/connectors/outbox-connector/status
```

### Чек-лист нового события

1. Объявить `@dataclass(frozen=True)`-событие рядом с моделью, задать `__event_name__` (`<модуль>.<агрегат>.<действие>`, минимум 3 сегмента) и `get_partition_key()`.
2. Вызвать `register_event()` в фабричном методе/методе модели.
3. В команде: `await event_bus.publish(model.pull_events())` **до** `await session.commit()`.
4. Проверить, что payload сериализуем (`asdict` + `additionally_serialize`).
5. Добавить имя топика и `group_id` в `config.py` модуля-потребителя.
6. Написать FastStream-подписчик с `EventIdempotencyGuard`, подключить его роутер в `app/consumers.py` → `setup_router()`.
7. Покрыть тестом: команда пишет строку в `outbox_messages`; подписчик идемпотентен при повторной доставке.

Подписчики тестируются так же, как HTTP-роуты. В `tests/conftest.py` `test_app()` собирает приложение продовым `setup_router()` из `app/main.py`, а `test_broker()` — брокер продовым `setup_router()` из `app/consumers.py`; фикстура `consumer_broker` поднимает над ним `TestKafkaBroker` с тестовым DI-контейнером:

```python
class TestMyConsumer:
    async def test_event_is_handled(self, consumer_broker: KafkaBroker) -> None:
        await consumer_broker.publish(message, topic=my_config.SOME_TOPIC)
```

Список роутеров в тестах не дублируется — значит, консьюмер, забытый в `setup_router()`, свои тесты не пройдёт.

---

## Core Services

### Кэширование (CacheRepository)

```python
from app.core.db.repository import CacheRepository, IRepository

class UserRepository(IRepository[User], CacheRepository):
    ...
```

После этого методы доступны прямо в query-хендлере как `self.user_repository.cache_paginated(...)` (см. разбор [`GetListUserQueryHandler`](#2-пошаговое-создание)).

| Метод | Когда использовать |
|---|---|
| `cache(type_model, func, ttl=60, *args, **kwargs)` | Кэширование одного Pydantic-объекта: ключ строится автоматически по модели/функции/аргументам (`_build_key`). |
| `cache_paginated(type_model, func, ttl=60, *args, **kwargs)` | То же для `PageResult[...]` (списки с пагинацией). |
| `cache_with_key(key, ...)` / `cache_with_key_paginated(key, ...)` | Те же операции с явно заданным ключом — когда нужен предсказуемый/переиспользуемый ключ. |
| `invalidate_cache(*keys)` | Без аргументов — инкрементирует версию списков (`_LIST_VERSION_KEY`), из-за чего все ранее выданные ключи модели становятся недостижимыми; с ключами — удаляет конкретные записи. Вызывайте после `create/update/delete`. |

Ключ имеет вид `cache:<DTO>:ver=<version>:<module>.<qualname>:<sha256(args)>`, поэтому:

- `func` должна быть awaitable-функцией **без побочных проверок доступа** (паттерн `handle` / `_handle`) — она вызывается только при промахе кэша;
- в неё передаются только те аргументы, которые влияют на **содержимое** ответа (фильтр, id), но не авторизационный контекст;
- результат сериализуется через `model_dump_json()` (`PageResult` — через `orjson` с полями `items/total/page/page_size`).

Rate limiting (`fastapi-limiter`) использует тот же Redis, но инициализируется отдельно в `lifespan`.

---

### Queue Service

**Используется:** [Taskiq](https://taskiq-python.github.io) + [taskiq-redis](https://github.com/taskiq-python/taskiq-redis)

**Создание задачи:**

```python
from dataclasses import dataclass
from app.core.services.queues.task import BaseTask

@dataclass
class ResizeImage(BaseTask):
    __task_name__ = "image.resize"

    @staticmethod
    @inject
    async def run(file_key: str, width: int, storage: FromDishka[StorageService]) -> None:
        ...
```

**Регистрация** — в `app/core/tasks.py` → `register_tasks(broker)`, который делегирует в `register_<module>_tasks(broker)` каждого модуля.

**Периодические задачи** задаются при регистрации через `schedule=[{"cron": ...}]` — так, например, зарегистрирована очистка outbox (`app/core/outbox/task.py`):

```python
broker.register_task(
    OutboxCleanupTask.run,
    OutboxCleanupTask.get_name(),
    schedule=[{"cron": f"*/{app_config.OUTBOX_CLEANUP_INTERVAL_SECONDS // 60} * * * *"}],
)
```

**Отправка в очередь:**

```python
from app.core.services.queues.service import QueueService

await queue_service.push(
    task=ResizeImage,
    data={"file_key": "uploads/photo.jpg", "width": 800},
)
```

`QueueService` также умеет `is_ready(task_id)`, `get_result(task_id)`, `wait_result(task_id, ...)`.

В тестовом окружении (`ENVIRONMENT=testing`) вместо Redis-брокера используется `InMemoryBroker`.

---

### Mail Service

**Используется:** [aiosmtplib](https://aiosmtplib.readthedocs.io/en/stable) + [Jinja2](https://jinja.palletsprojects.com)

**Создание шаблона:**

```python
from pathlib import Path
from app.core.services.mail.template import BaseTemplate

class WelcomeTemplate(BaseTemplate):
    def __init__(self, username: str) -> None:
        self.username = username

    def _get_dir(self) -> Path:
        return Path("app/my_module/emails/views")

    def _get_name(self) -> str:
        return "welcome.html"
```

HTML-шаблон (`welcome.html`):

```html
<h1>Привет, {{ username }}!</h1>
<p>Добро пожаловать.</p>
```

**Отправка:**

```python
from app.core.services.mail.service import BaseMailService, EmailData

email_data = EmailData(subject="Добро пожаловать", recipient=user.email)
template = WelcomeTemplate(username=user.username)

await mail_service.send(template=template, email_data=email_data)   # синхронно
await mail_service.queue(template=template, email_data=email_data)  # через очередь
```

---

### Storage Service

**Используется:** [MinIO](https://min.io) (S3-compatible) + [minio-py](https://github.com/minio/minio-py)

**Основные методы `StorageService`:**

| Метод | Описание |
|-------|----------|
| `upload_file(UploadFile)` | Загрузить файл, вернуть key или public URL |
| `upload_put_url(bucket, key, expires)` | Presigned PUT URL |
| `upload_post_file(UploadFilePost)` | Presigned POST (browser upload) |
| `generate_presigned_url(bucket, key, expires)` | Presigned GET URL |
| `delete_file(bucket, key)` | Удалить файл |
| `download(bucket, key)` / `download_range(...)` | Скачать целиком или диапазон байт |
| `download_to_path(...)` / `download_bytes(...)` | Скачать в файл / в память |
| `copy_object(...)` | Копирование объекта внутри хранилища |
| `get_stat(bucket, key)` | Метаданные объекта (`ObjectStat`) |
| `get_public_url_object(bucket, key)` | Публичный URL (для bucket-ов с READ-политикой) |

```python
from dishka import FromDishka
from app.core.services.storage.service import StorageService
from app.core.services.storage.dtos import UploadFile

@router.post("/upload")
async def upload(file: FastAPIUploadFile, storage: FromDishka[StorageService]):
    key = await storage.upload_file(UploadFile(
        bucket_name="base",
        file_content=file.file,
        file_key=f"uploads/{file.filename}",
        size=file.size,
        content_type=file.content_type,
    ))
    return {"file_key": key}
```

**Bucket Policies** (`app.core.services.storage.aminio.policy.Policy`):

`NONE` (private) | `GET` | `READ` | `WRITE` | `READ_WRITE`

Настраиваются в `CoreProvider`:

```python
@provide(scope=Scope.APP)
def bucket_policy(self) -> dict[str, Policy]:
    return {"base": Policy.NONE}
```

Медиа-файлы дополнительно проходят через `MediaProbeService` (`app/core/services/media`, реализация на `ffprobe`) — он определяет реальный тип/длительность/размеры до сохранения.

---

### WebSocket Service

`app/core/websocket/` — горизонтально масштабируемый WS-gateway. Каждый процесс `app` — отдельный **gateway** со своим `gateway_id` (`$GATEWAY_ID`/`$HOSTNAME` + pid), маршрутизация между gateway'ями идёт через **Redis Streams**, а не pub/sub, чтобы сообщения переживали кратковременный обрыв читателя и переклеймливались при падении процесса.

**Компоненты:**

| Компонент | Файл | Назначение |
|---|---|---|
| `WSConnection` | `websocket.py` | Одно соединение: очередь на отправку (`WS_SEND_QUEUE_SIZE`), writer-loop, heartbeat |
| `ConnectionManager` | `manager.py` | Реестр соединений процесса, подписки на каналы, чтение своего Redis-стрима, claim «зависших» записей, метрики |
| `PresenceService` | `presence.py` | Онлайн-присутствие пользователей в Redis (TTL `WS_PRESENCE_TTL`) |
| `WebsocketKeys` | `keys.py` | Схема ключей Redis (стрим gateway, маршруты, соединения) |
| `DeliveryDTO` | `dtos.py` | Формат доставляемого клиенту события |

**Основные методы `ConnectionManager`:**

`startup()` / `shutdown()` — фоновые циклы (обновление маршрутов, чтение стрима, claim pending, экспорт метрик); `register(conn)` / `unregister(conn)`; `subscribe_channel(conn, channel)` / `unsubscribe_channel(conn, channel)`; `send_to_users_local(...)` — доставка подключённым к этому процессу; `send_user_payload(event)` — доставка пользователю независимо от того, на каком gateway он висит.

`ConnectionManager` и `PresenceService` регистрируются в `CoreWSProvider` со `Scope.APP`; `startup()` поднимается в `lifespan` через `aiojobs.Scheduler`.

Поведение настраивается переменными `WS_*` в `AppConfig` (heartbeat, лимит соединений на пользователя, TTL записей в Redis, размеры и таймауты стрима). Метрики — `WS_ACTIVE_CONNECTIONS`, `WS_ACTIVE_SUBSCRIPTIONS`, `WS_CONNECTION_EVICTIONS`, `WS_DELIVERY_LATENCY`, `WS_GATEWAY_STREAM_*` (`app/core/metrics.py`).

---

### Message Brokers

**Используется:** Kafka. Продюсер — [aiokafka](https://github.com/aio-libs/aiokafka) (`KafkaMessageBroker`), консьюмеры — [FastStream](https://faststream.ag2.ai) (`app/consumers.py`).

`BaseMessageBroker` (`app/core/message_brokers/base.py`) — интерфейс продюсера:

| Метод | Назначение |
|---|---|
| `send_message(key, topic, value)` | Отправить готовые байты |
| `send_data(key, topic, data)` | Отправить произвольный dict (orjson) |
| `send_event(key, topic, event)` | Отправить `BaseEvent` |
| `send_many(records)` | Батч `BrokerRecord`; возвращает список ошибок по позициям |
| `start_consuming(topics)` / `stop_consuming()` | Низкоуровневое чтение (для служебных сценариев) |
| `start()` / `close()` | Управляются `lifespan`-ом процесса |

```python
from dishka import FromDishka
from app.core.message_brokers.base import BaseMessageBroker

async def notify(broker: FromDishka[BaseMessageBroker]) -> None:
    await broker.send_data(key="chat_1", topic="chats.offline-delivery", data={"action": "created"})
```

> **Важно.** Прямой `send_*` — это транспорт для служебных/производных сообщений (например, fan-out уже обработанного события между процессами). **Доменные события так публиковать нельзя** — они всегда идут через outbox, см. [Событийная архитектура](#событийная-архитектура-outbox--wal--debezium). Отправка в Kafka из хендлера не участвует в транзакции БД, поэтому даёт рассинхрон при откате или падении.

Чтение сообщений — только через FastStream-подписчики (`<module>/consumers/*.py`), которые дают DI, метрики, ретраи и управление offset-ами; `start_consuming()` в прикладном коде не используется.

---

### Logging Service

**Используется:** [structlog](https://www.structlog.org/en/stable)

Настройка в `app/core/log/init.py` (`configure_logging()`). Поддерживает JSON и console-рендеринг, файловый хендлер, интеграцию с `ContextMiddleware` для добавления `request_id`.

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Something happened", extra={"user_id": 42})
logger.error("Error occurred", exc_info=True)
```

---

### Monitoring

**Prometheus.** У процесса `app` метрики отдаёт `prometheus-fastapi-instrumentator` (сами `/health` и `/metrics` из наблюдения исключены):

```python
# app/main.py
PrometheusFastApiInstrumentator(
    excluded_handlers=[r"^/health$", r"^/metrics$"]
).instrument(app, latency_lowr_buckets=(0.1, 0.5, 1, 1.5, 2, 2.5, 3)).expose(app, should_gzip=True, tags=["core"])
```

Процесс `consumers` поднимает собственный `/metrics` (ASGI-роут FastStream, порт `9002`) с `KafkaPrometheusMiddleware`.

**Доменные метрики:**

| Метрика | Процесс | Смысл |
|---|---|---|
| `outbox_events_written_total{topic,event_name}` | `app` | События, записанные в outbox |
| `outbox_cleanup_deleted_total` | `scheduler` | Строки, удалённые ретенцией |
| `ws_active_connections`, `ws_active_subscriptions` | `app` | Состояние WebSocket-gateway |
| `ws_connection_evictions`, `ws_delivery_latency` | `app` | Отключения и задержка доставки |
| `ws_gateway_stream_*` | `app` | Длина, pending и claim Redis-стрима gateway'я |

Состояние CDC-конвейера смотрится не в Prometheus, а через Kafka Connect REST API: `GET localhost:8083/connectors/outbox-connector/status`.

**Health check:**

```
GET /health → 200 "Ok"
```

В директории `monitoring/` расположены конфиги Grafana, Loki, Vector и Prometheus.

---

### Middleware

**Встроенные middleware (порядок регистрации → порядок выполнения LIFO):**

| Middleware | Назначение |
|-----------|-----------|
| `ContextMiddleware` | Генерирует `request_id` (UUID), добавляет в `scope["state"]` и заголовок `x-request-id` |
| `GZipMiddleware` | Сжатие ответов ≥ 1000 байт |
| `CORSMiddleware` | Добавляется если задан `BACKEND_CORS_ORIGINS` |
| `LoggingMiddleware` | Логирует метод, путь, статус и время обработки каждого запроса |

Реализованы как ASGI middleware (без `BaseHTTPMiddleware`).

```python
# app/main.py
def setup_middleware(app: FastAPI) -> None:
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    if app_config.BACKEND_CORS_ORIGINS:
        app.add_middleware(CORSMiddleware, ...)
    app.add_middleware(ContextMiddleware)  # выполняется первым
```

---

## Application Lifecycle

Приложение состоит из четырёх процессов; у каждого свой lifecycle.

### Процесс app (HTTP + WebSocket)

`app/main.py`. `init_app()` до старта сервера: настраивает Prometheus-инструментатор, логирование, создаёт Dishka-контейнер (`create_container()`), регистрирует middleware, роутеры и exception-хендлеры.

`lifespan` на старте:

1. **FastAPILimiter** — инициализация Redis-клиента для rate limiting.
2. **Message broker** — `BaseMessageBroker.start()` (Kafka producer/consumer).
3. **WebSocket-gateway** — `ConnectionManager.startup()` запускается фоновой задачей через `aiojobs.Scheduler`.

На остановке: `scheduler.close()` → `redis_client.aclose()` → `message_broker.close()` → `dishka_container.close()`.

### Процесс consumers (FastStream)

`app/consumers.py`. `init_app()` создаёт `KafkaBroker` с `KafkaPrometheusMiddleware`, подключает роутеры-подписчики модулей и Dishka (`setup_dishka(..., auto_inject=True)`). В `lifespan` стартует `BaseMessageBroker`, метрики отдаются на `/metrics` ASGI-роуте.

### Процессы queue_worker и scheduler (Taskiq)

`app/tasks.py`. Общий модуль: создаёт контейнер с `TaskiqProvider`, поднимает/останавливает `BaseMessageBroker` на `WORKER_STARTUP`/`WORKER_SHUTDOWN`. Расписание берётся из `RedisScheduleSource` + `LabelScheduleSource` (в `ENVIRONMENT=testing` — только label-source).

### Миграции и первичные данные

Выполняются отдельным one-shot контейнером `migrations`, а не при старте приложения:

```bash
alembic upgrade head && python -m app.init_data
```

`app/pre_start.py` — retry-проверка доступности БД (tenacity), вызывается из `init_data()`.
`app/init_data.py` — создаёт базовые роли из `RolesEnum` (`super_admin`, `system_admin`, `user`).

---

## Создание нового модуля

### 1. Структура модуля

```
new_module/
├── models/              # ORM-модели (+ объявления доменных событий рядом с моделью)
├── dtos/                # Внутренние DTO (Pydantic)
├── schemas/             # Request / Response схемы
│   └── <entity>/
│       ├── requests.py
│       └── responses.py
├── filters/             # Filter-классы
├── repositories/        # Репозитории (SQLAlchemy + Redis)
├── commands/            # Command + CommandHandler
│   └── <entity>/
├── queries/             # Query + QueryHandler
│   └── <entity>/
├── consumers/           # FastStream-подписчики на Kafka-топики (реакция на события)
├── tasks/               # (опционально) фоновые Taskiq-задачи
├── emails/              # (опционально) шаблоны писем
│   ├── templates.py
│   └── views/
├── services/            # (опционально) доменные сервисы модуля
├── __init__.py
├── config.py            # (опционально) ModuleConfig(BaseConfig) — в т.ч. имена топиков и group_id
├── exceptions.py
├── deps.py              # FastAPI-зависимости
├── providers.py         # Dishka-провайдер
├── routers.py           # Агрегирующий роутер
└── tasks.py             # Регистрация Taskiq-задач (register_<module>_tasks)
```

> Межмодульное взаимодействие идёт **через события в Kafka** (см. [Событийная архитектура](#событийная-архитектура-outbox--wal--debezium)), а не через прямые импорты чужих репозиториев. Синхронный доступ допустим только через порт в `app/core` (как `RBACManagerInterface`), реализация которого регистрируется через `alias(...)` в провайдере модуля.

### 2. Пошаговое создание

**1. Модель и её доменные события:**

```python
from app.core.db.base_model import BaseModel, DateMixin
from app.core.events.event import BaseEvent


@dataclass(frozen=True)
class ArticleCreatedEvent(BaseEvent):
    article_id: int
    author_id: int

    __event_name__: str = "articles.article.created"   # <модуль>.<агрегат>.<действие>

    def get_partition_key(self) -> str:
        return str(self.article_id)


class Article(BaseModel, DateMixin):
    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))

    @classmethod
    def create(cls, title: str, author_id: int) -> "Article":
        article = cls(title=title, author_id=author_id)
        article.register_event(ArticleCreatedEvent(article_id=article.id, author_id=author_id))
        return article
```

Зарегистрировать модель в `app/core/models.py` — иначе Alembic её не увидит.

**2. Фильтр:**

```python
@dataclass
class ArticleFilter(BaseFilter):
    title: str | None = None

    def build_condition(self) -> None:
        self.add_condition("title", FilterOperator.CONTAINS, self.title)
```

**3. Репозиторий:**

```python
@dataclass
class ArticleRepository(IRepository[Article], CacheRepository):
    async def create(self, article: Article) -> None:
        self.session.add(article)

    def apply_relationship_filters(self, stmt: Select, filters: ArticleFilter) -> Select:
        return stmt
```

`CacheRepository` подмешивается, только если репозиторию действительно нужен кэш (см. [Кэширование](#кэширование-cacherepository)).

**4. Command + Handler:**

```python
@dataclass(frozen=True)
class CreateArticleCommand(BaseCommand):
    title: str
    user_id: int

@dataclass(frozen=True)
class CreateArticleCommandHandler(BaseCommandHandler[CreateArticleCommand, ArticleDTO]):
    session: AsyncSession
    event_bus: BaseEventBus
    article_repository: ArticleRepository

    async def handle(self, command: CreateArticleCommand) -> ArticleDTO:
        article = Article.create(title=command.title, author_id=command.user_id)
        await self.article_repository.create(article)

        await self.event_bus.publish(article.pull_events())   # INSERT в outbox
        await self.session.commit()                           # один коммит на данные + события
        await self.article_repository.invalidate_cache()

        return ArticleDTO.model_validate(article)
```

Порядок важен: `publish()` кладёт строки в `outbox_messages` через тот же `AsyncSession`, поэтому вызывается **до** `commit()`. Инвалидация кэша — после успешного коммита.

**4.1. Query + Handler (пагинация + кэш + RBAC):**

Пока `Command` выше отвечает за запись, `Query` отвечает только за чтение — и часто требует пагинацию, кэширование и проверку прав. Ниже — реальный обработчик из `app/auth/queries/users/get_list.py`, разобранный построчно.

```python
from dataclasses import dataclass

from app.auth.dtos.user import AuthUserJWTData, UserDTO
from app.auth.filters.users import UserFilter
from app.auth.models.user import User
from app.auth.repositories.user import UserRepository
from app.auth.services.rbac import AuthRBACManager
from app.core.db.repository import PageResult
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.exceptions import AccessDeniedError


@dataclass(frozen=True)
class GetListUserQuery(BaseQuery):
    user_filter: UserFilter
    user_jwt_data: AuthUserJWTData


@dataclass(frozen=True)
class GetListUserQueryHandler(BaseQueryHandler[GetListUserQuery, PageResult[UserDTO]]):
    user_repository: UserRepository
    rbac_manager: AuthRBACManager

    async def handle(self, query: GetListUserQuery) -> PageResult[UserDTO]:
        if not self.rbac_manager.check_permission(query.user_jwt_data, {"user:view"}):
            raise AccessDeniedError(need_permissions={"user:view"} - set(query.user_jwt_data.permissions))

        return await self.user_repository.cache_paginated(
            UserDTO, self._handle, ttl=200,
            user_filter=query.user_filter,
        )

    async def _handle(self, user_filter: UserFilter) -> PageResult[UserDTO]:
        pagination_users = await self.user_repository.find_by_filter(
            User,
            filters=user_filter
        )

        return PageResult(
            items=[UserDTO.model_validate(user) for user in pagination_users.items],
            total=pagination_users.total,
            page=pagination_users.page,
            page_size=pagination_users.page_size
        )
```

Разбор по частям:

- **`GetListUserQuery`** — как и любой `BaseQuery`, это неизменяемый (`frozen=True`) dataclass. Он не содержит логики — только данные, необходимые обработчику: уже собранный `UserFilter` (см. [Filter System](#filter-system)) и JWT-данные текущего пользователя `AuthUserJWTData` (нужны для проверки прав внутри хендлера).
- **`GetListUserQueryHandler`** наследует `BaseQueryHandler[GetListUserQuery, PageResult[UserDTO]]` — типизированный контракт «на входе `GetListUserQuery`, на выходе `PageResult[UserDTO]`». Зависимости (`UserRepository`, `AuthRBACManager`) объявлены как обычные поля dataclass и подставляются Dishka через `providers.py` — никакого ручного создания сервисов внутри хендлера.
- **Проверка прав — первым делом в `handle`, до кэша.** `rbac_manager.check_permission(...)` вызывается в публичном `handle`, а не в закэшированном `_handle`. Это важно: если бы проверка была внутри `_handle`, при попадании в кэш (cache hit) она бы вообще не выполнилась, и второй пользователь без нужных прав получил бы чужой закэшированный ответ. При отсутствии прав выбрасывается `AccessDeniedError(need_permissions=...)` — глобальный exception-хендлер сам превратит её в HTTP 403 (см. `app/core/exceptions.py`).
- **Разделение `handle` / `_handle`.** Публичный `handle` = «проверить права → вызвать `cache_paginated`». Приватный `_handle` = «чистая» функция без побочных проверок, которую `cache_paginated` вызывает только при промахе кэша (cache miss) и результат которой сериализуется в Redis. Такое разделение — стандартный паттерн для любого читающего хендлера, где нужен и RBAC, и кэш.
- **В кэш и в `_handle` передаётся только `user_filter`, а не весь `query`.** Это специально: ключ кэша строится из тех же `*args/**kwargs`, что передаются в закэшированную функцию (см. ниже), поэтому в него нельзя передавать `query` целиком — внутри него лежит `user_jwt_data` (роли/права конкретного пользователя). Если бы ключ включал JWT-данные, кэш почти никогда бы не переиспользовался между пользователями (а с учётом того, что `roles`/`permissions` собираются в `set` — ещё и был бы нестабилен между запусками процесса из-за рандомизации хэшей). Правило: в кэшируемую функцию передаются только параметры, которые действительно влияют на *содержимое* ответа; авторизационный контекст туда не попадает — он уже проверен строкой выше.
- **`user_repository.cache_paginated(UserDTO, self._handle, ttl=200, user_filter=query.user_filter)`** — обёртка из `CacheRepository` (`app/core/db/repository.py`, подмешивается в каждый `IRepository`). Она сама строит ключ кэша на основе имени модели DTO, модуля/имени функции (`self._handle`) и хэша переданных аргументов (`user_filter`), проверяет Redis, а при промахе вызывает `self._handle(user_filter=user_filter)`, сохраняет `PageResult` в Redis на `ttl` секунд и возвращает результат. При изменении данных кэш инвалидируется через `invalidate_cache()` (инкремент версии), что делает все ранее выданные ключи для этой модели «протухшими» без явного удаления каждого ключа.
- **`find_by_filter(User, filters=user_filter)`** — общий метод `IRepository` (не специфичный для `User`): строит `SELECT` с учётом `loading_config` фильтра (жадная подгрузка связей), применяет условия из фильтра, считает `COUNT(*)` для `total`, применяет сортировку и `OFFSET/LIMIT` из `filters.pagination`, и возвращает уже готовый `PageResult[User]` — конвертация в DTO происходит уровнем выше, в `_handle`.
- **Маппинг в DTO.** Каждая ORM-модель конвертируется явно: `UserDTO.model_validate(user)`. Хендлеры никогда не возвращают ORM-модели наружу — только DTO/Pydantic-схемы.

**Правило для любого нового кэширующего query-хендлера:** в `cache`/`cache_paginated` передавайте явными kwargs только то подмножество параметров запроса, которое влияет на данные (фильтр, id и т.п.). Никогда не передавайте туда весь `Query`/`Command` целиком, если внутри есть JWT-данные, объект пользователя или что-то ещё, что делает ключ кэша шире, чем реально нужно.

Используйте этот файл (`app/auth/queries/users/get_list.py`) как образец для любого нового «списочного» query-хендлера с пагинацией: `GetListArticlesQuery` / `GetListArticlesQueryHandler` в новом модуле строятся ровно по этой же схеме.

**5. DI-провайдер:**

```python
class ArticleModuleProvider(Provider):
    scope = Scope.REQUEST

    article_repository = provide(ArticleRepository)
    create_handler = provide(CreateArticleCommandHandler)
    get_list_handler = provide(GetListArticlesQueryHandler)

    @decorate
    def register_commands(self, registry: CommandRegistry) -> CommandRegistry:
        registry.register_command(CreateArticleCommand, CreateArticleCommandHandler)
        return registry

    @decorate
    def register_queries(self, registry: QueryRegistry) -> QueryRegistry:
        registry.register_query(GetListArticlesQuery, GetListArticlesQueryHandler)
        return registry
```

**6. Роутер:**

```python
router = APIRouter(prefix="/articles", route_class=DishkaRoute)

@router.post("/", status_code=201)
async def create_article(
    data: ArticleCreateRequest,
    mediator: FromDishka[BaseMediator],
) -> ArticleResponse:
    dto = await mediator.handle_command(CreateArticleCommand(title=data.title, user_id=...))
    return ArticleResponse.model_validate(dto)
```

**7. Подписчик на события (если модуль на что-то реагирует):**

```python
# app/articles/consumers/profiles.py
router = KafkaRouter()

@router.subscriber(article_config.PROFILE_TOPIC, group_id=article_config.PROFILE_GROUP_ID)
@inject
async def on_profile_updated(
    event: TypedEventDTO[ProfilePayload],
    mediator: FromDishka[BaseMediator],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if not await idempotency_guard.try_acquire(
        group=article_config.PROFILE_GROUP_ID, event_id=event.event_id
    ):
        return
    await mediator.handle_command(UpsertAuthorProjectionCommand(...))
```

**8. Регистрация модуля** — в трёх точках:

```python
# app/core/di/container.py
from app.articles.providers import ArticleModuleProvider

def create_container(*app_providers: Provider) -> AsyncContainer:
    providers = [
        *get_core_providers(),
        AuthModuleProvider(),
        ArticleModuleProvider(),   # ← добавить
    ]
    return make_async_container(*providers, *app_providers)

# app/main.py — HTTP-роуты
from app.articles.routers import router_v1 as article_router_v1

def setup_router(app: FastAPI) -> None:
    app.include_router(auth_router_v1, prefix=app_config.API_V1_STR)
    app.include_router(article_router_v1, prefix=app_config.API_V1_STR)   # ← добавить

# app/consumers.py — подписчики Kafka
from app.articles.consumers import profiles

def setup_router(broker: KafkaBroker) -> None:
    broker.include_router(profiles.router)   # ← добавить

# app/core/tasks.py — фоновые задачи
from app.articles.tasks import register_article_tasks

def register_tasks(broker: AsyncBroker) -> None:
    register_article_tasks(broker)   # ← добавить
```

### 3. Соглашения по именованию

| Элемент | Стиль | Пример |
|---------|-------|--------|
| Модуль | существительное (мн. число) | `articles`, `orders` |
| Команда | глагол + существительное | `CreateArticleCommand`, `PublishPostCommand` |
| Query | `Get` + существительное | `GetListArticlesQuery`, `GetArticleByIdQuery` |
| Класс события | действие в прош. времени + сущность + `Event` | `CreatedUserEvent`, `VerifiedUserEvent` |
| `__event_name__` | `<модуль>.<агрегат>.<действие>` (3 сегмента, прош. время) | `auth.user.created`, `profiles.profile.updated` |
| Kafka-топик | первый сегмент имени события (выводится автоматически) | `auth`, `profiles`, `chats` |
| `group_id` подписчика | назначение подписчика, а не имя модуля | `delivery-router`, `offline-push` |
| Класс задачи | действие + `Task` | `OutboxCleanupTask`, `PushOfflineRecipientsTask` |
| `__task_name__` | `<домен>.<действие>` | `outbox.cleanup`, `image.resize` |
| Фильтр | существительное + `Filter` | `ArticleFilter` |
| Репозиторий | существительное + `Repository` | `ArticleRepository` |

Имена топиков и `group_id` объявляются в `config.py` модуля (`BaseConfig`) и переопределяются через `.env`, а не хардкодятся в подписчике.