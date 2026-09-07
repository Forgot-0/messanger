"""
Сидинг данных для нагрузочного теста app/chats (п.2 промпта).

Создаёт напрямую в БД (без прохождения auth-флоу — это не предмет теста):
  - N пользователей (роль "user", как при обычной регистрации);
  - M direct-чатов (по 2 участника);
  - K групповых чатов размером НИЖЕ FAN_OUT_WRITE_THRESHOLD (fanout_on_write);
  - S супергрупп размером ВЫШЕ порога (active_subscribers);
  - C каналов размером ВЫШЕ порога (channel_subscribers) — опционально, только
    для полноты картины: в канале писать может лишь owner/staff
    (role_id 1/2/3), обычные участники сидят VIEWER-ом (message:send=False),
    поэтому сценарий (b) по умолчанию гоняется против group/supergroup, а
    канал — дополнительный, второстепенный кейс (см. loadtests/README.md).

N/M/K и все размеры — параметры командной строки, не константы (п.2).

Все ORM-модели (Chat/ChatMember/User/...) в проекте пишутся через async ORM +
outbox-паттерн (модели публикуют события в outbox при commit). Сидинг
намеренно ИДЁТ В ОБХОД этого пути и пишет напрямую через asyncpg bulk-insert:
это на порядки быстрее для тысяч строк и не должно порождать outbox-события/
Kafka-трафик — сидинг это подготовка стенда, а не часть измеряемого сценария.

ВАЖНО про chat_members.banned_to/muted_to: в модели ChatMember "забанен"/"замьючен"
означает banned_to IS NULL OR banned_to > now() (см. app/chats/models/chat_members.py
:: is_banned/is_muted) — то есть NULL воспринимается как "забанен навсегда",
а не как "не забанен"! ChatMember.create() поэтому явно проставляет
banned_to=muted_to=now() при создании. Сидинг обязан делать то же самое —
иначе все участники окажутся забанены и не смогут ни писать, ни читать.

ВАЖНО про enum chattype в БД: alembic-миграция создаёт тип chattype со
значениями 'DIRECT'/'GROUP'/'SUPERGROUP'/'CHANNEL' (member.name Python-enum'а,
а не member.value вида "direct"/"group") — используем ИМЕНА, не values.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid7

import asyncpg

from app.core.configs.app import app_config
from app.core.utils import now_utc

STANDARD_USER_ROLE_NAME = "user"

CHAT_ROLE_OWNER = 1
CHAT_ROLE_DIRECT_MEMBER = 4
CHAT_ROLE_MEMBER = 5
CHAT_ROLE_VIEWER = 6

DEFAULT_MANIFEST_PATH = "loadtests/data/manifest.json"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    p.add_argument("--users", type=int, default=6000, help="N: сколько пользователей создать")

    p.add_argument("--direct-chats", type=int, default=1500, help="M: сколько direct-чатов создать")

    p.add_argument("--group-chats", type=int, default=60, help="K: сколько групповых чатов (fanout_on_write)")
    p.add_argument("--group-min-size", type=int, default=5)
    p.add_argument(
        "--group-max-size", type=int, default=499,
        help="Строго меньше FAN_OUT_WRITE_THRESHOLD=500 (иначе это уже не fanout_on_write, "
             "хотя из-за MAX_GROUP_MEMBERS=500 группа физически не может стать active_subscribers)",
    )

    p.add_argument("--supergroups", type=int, default=6, help="S: сколько супергрупп (active_subscribers)")
    p.add_argument("--supergroup-min-size", type=int, default=600)
    p.add_argument("--supergroup-max-size", type=int, default=4000)

    p.add_argument("--channels", type=int, default=2, help="C: сколько каналов (channel_subscribers)")
    p.add_argument("--channel-min-size", type=int, default=600)
    p.add_argument("--channel-max-size", type=int, default=4000)

    p.add_argument(
        "--tag",
        default=datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="Уникальный префикс для username/email этого прогона сидинга (по умолчанию — таймстамп)",
    )
    p.add_argument("--manifest-out", default=DEFAULT_MANIFEST_PATH, help="Куда записать manifest.json")
    p.add_argument("--batch-size", type=int, default=2000, help="Размер батча для bulk-insert'ов")

    p.add_argument(
        "--cleanup",
        action="store_true",
        help="Вместо сидинга — удалить всё, что перечислено в --manifest-out, и сам файл манифеста",
    )

    return p.parse_args()


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def chunks(seq: list, size: int) -> list[list]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


@dataclass
class SeededChat:
    id: str
    kind: str
    owner_id: int
    member_ids: list[int]


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=app_config.POSTGRES_SERVER,
        port=app_config.POSTGRES_PORT,
        user=app_config.POSTGRES_USER,
        password=app_config.POSTGRES_PASSWORD,
        database=app_config.POSTGRES_DB,
    )


# ─── Сидинг ──────────────────────────────────────────────────────────────────

async def seed_users(conn: asyncpg.Connection, tag: str, count: int, batch_size: int) -> list[int]:
    print(f"[seed] создаю {count} пользователей (tag={tag})...")

    role_id = await conn.fetchval("SELECT id FROM roles WHERE name = $1", STANDARD_USER_ROLE_NAME)
    if role_id is None:
        raise RuntimeError(
            f"В таблице roles нет роли {STANDARD_USER_ROLE_NAME!r}. Похоже, миграции/init_data "
            f"ещё не применены — сначала прогоните `docker compose ... run migrations` "
            f"(alembic upgrade head && python -m app.init_data)."
        )

    all_ids: list[int] = []
    for batch_no, idx_batch in enumerate(chunks(list(range(count)), batch_size)):
        emails = [f"lt-{tag}-{i}@loadtest.local" for i in idx_batch]
        usernames = [f"lt_{tag}_{i}" for i in idx_batch]

        rows = await conn.fetch(
            """
            INSERT INTO users (email, username, password_hash, is_active, is_verified)
            SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::bool[], $5::bool[])
            RETURNING id
            """,
            emails,
            usernames,
            [None] * len(idx_batch),
            [True] * len(idx_batch),
            [True] * len(idx_batch),
        )
        batch_ids = [r["id"] for r in rows]
        all_ids.extend(batch_ids)

        await conn.execute(
            """
            INSERT INTO user_roles (user_id, role_id)
            SELECT * FROM unnest($1::bigint[], $2::bigint[])
            """,
            batch_ids,
            [role_id] * len(batch_ids),
        )
        print(f"  ...{len(all_ids)}/{count}")

    return all_ids


async def _insert_chats_batch(
    conn: asyncpg.Connection,
    chats: list[SeededChat],
) -> None:
    await conn.execute(
        """
        INSERT INTO chats (
            id, seq_counter, type, name, description, is_public, created_by,
            member_count, admin_only, slow_mode_seconds, permissions, reactions_mode
        )
        SELECT * FROM unnest(
            $1::uuid[], $2::bigint[], $3::chattype[], $4::text[], $5::text[],
            $6::bool[], $7::bigint[], $8::int[], $9::bool[], $10::int[], $11::jsonb[], $12::chatreactionsmode[]
        )
        """,
        [c.id for c in chats],
        [0] * len(chats),
        [c.kind.upper() for c in chats],  # chattype enum хранит ИМЕНА (DIRECT/GROUP/...), не values
        [f"[loadtest] {c.kind} {c.id}" for c in chats],
        [None] * len(chats),
        [False] * len(chats),
        [c.owner_id for c in chats],
        [len(c.member_ids) for c in chats],
        [False] * len(chats),
        [0] * len(chats),
        ["{}"] * len(chats),
        ["ALL"] * len(chats)
    )


async def _insert_members_batch(
    conn: asyncpg.Connection,
    chat_ids: list[str],
    user_ids: list[int],
    role_ids: list[int],
    at: datetime,
) -> None:
    n = len(chat_ids)
    await conn.execute(
        """
        INSERT INTO chat_members (chat_id, user_id, role_id, muted_to, banned_to, permissions_overrides)
        SELECT * FROM unnest($1::uuid[], $2::bigint[], $3::bigint[], $4::timestamptz[], $5::timestamptz[], $6::jsonb[])
        """,
        chat_ids,
        user_ids,
        role_ids,
        [at] * n,
        [at] * n,  # см. докстринг модуля: banned_to/muted_to = "сейчас", а не NULL
        ["{}"] * n,
    )


async def seed_chats(
    conn: asyncpg.Connection,
    user_ids: list[int],
    kind: str,
    count: int,
    min_size: int,
    max_size: int,
    owner_role_id: int,
    member_role_id: int,
    batch_size: int,
    rng: random.Random,
) -> list[SeededChat]:
    if count == 0:
        return []

    print(f"[seed] создаю {count} чатов типа {kind} (участников: {min_size}..{max_size})...")

    if max_size > len(user_ids):
        raise RuntimeError(
            f"--{kind}-max-size={max_size} больше, чем количество пользователей ({len(user_ids)}). "
            f"Увеличьте --users или уменьшите размер {kind}."
        )

    chats: list[SeededChat] = []
    for _ in range(count):
        size = rng.randint(min_size, max_size)
        members = rng.sample(user_ids, size)
        owner = members[0]
        rest = members[1:]
        chats.append(SeededChat(id=str(uuid7()), kind=kind, owner_id=owner, member_ids=[owner, *rest]))

    at = now_utc()
    for batch in chunks(chats, batch_size):
        await _insert_chats_batch(conn, batch)

        chat_id_col: list[str] = []
        user_id_col: list[int] = []
        role_id_col: list[int] = []
        for c in batch:
            chat_id_col.append(c.id)
            user_id_col.append(c.owner_id)
            role_id_col.append(owner_role_id)
            for m in c.member_ids[1:]:
                chat_id_col.append(c.id)
                user_id_col.append(m)
                role_id_col.append(member_role_id)

        await _insert_members_batch(conn, chat_id_col, user_id_col, role_id_col, at)
        print(f"  ...{len(chats)} чатов подготовлено, последний батч по {len(batch)} записан")

    return chats


async def seed_direct_chats(
    conn: asyncpg.Connection,
    user_ids: list[int],
    count: int,
    batch_size: int,
    rng: random.Random,
) -> list[SeededChat]:
    if count == 0:
        return []
    if len(user_ids) < 2:
        raise RuntimeError("Нужно минимум 2 пользователя для direct-чатов")

    print(f"[seed] создаю {count} direct-чатов...")

    chats: list[SeededChat] = []
    for _ in range(count):
        a, b = rng.sample(user_ids, 2)
        chats.append(SeededChat(id=str(uuid7()), kind="direct", owner_id=a, member_ids=[a, b]))

    at = now_utc()
    for batch in chunks(chats, batch_size):
        await _insert_chats_batch(conn, batch)

        chat_id_col, user_id_col, role_id_col = [], [], []
        for c in batch:
            for m in c.member_ids:
                chat_id_col.append(c.id)
                user_id_col.append(m)
                role_id_col.append(CHAT_ROLE_DIRECT_MEMBER)

        await _insert_members_batch(conn, chat_id_col, user_id_col, role_id_col, at)

    return chats


# ─── Manifest ────────────────────────────────────────────────────────────────

def write_manifest(
    path: str,
    tag: str,
    user_ids: list[int],
    direct: list[SeededChat],
    group: list[SeededChat],
    supergroup: list[SeededChat],
    channel: list[SeededChat],
) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "tag": tag,
        "created_at": now_utc().isoformat(),
        "users": [{"id": uid, "username": f"lt_{tag}_{i}"} for i, uid in enumerate(user_ids)],
        "chats": {
            "direct": [{"id": c.id, "owner_id": c.owner_id, "member_ids": c.member_ids} for c in direct],
            "group": [{"id": c.id, "owner_id": c.owner_id, "member_ids": c.member_ids} for c in group],
            "supergroup": [{"id": c.id, "owner_id": c.owner_id, "member_ids": c.member_ids} for c in supergroup],
            "channel": [{"id": c.id, "owner_id": c.owner_id, "member_ids": c.member_ids} for c in channel],
        },
    }
    out.write_text(json.dumps(manifest, indent=2))
    print(f"[seed] manifest записан в {out.resolve()}")


# ─── Cleanup ─────────────────────────────────────────────────────────────────

async def cleanup(conn: asyncpg.Connection, manifest_path: str) -> None:
    path = Path(manifest_path)
    if not path.exists():
        print(f"[cleanup] {path} не найден, нечего удалять")
        return

    data = json.loads(path.read_text())
    chat_ids = [
        c["id"]
        for kind in ("direct", "group", "supergroup", "channel")
        for c in data["chats"].get(kind, [])
    ]
    user_ids = [u["id"] for u in data["users"]]

    print(f"[cleanup] удаляю {len(chat_ids)} чатов и {len(user_ids)} пользователей (tag={data['tag']})...")

    async with conn.transaction():
        for batch in chunks(chat_ids, 5000):
            await conn.execute("DELETE FROM chat_members WHERE chat_id = ANY($1::uuid[])", batch)
            await conn.execute("DELETE FROM messages WHERE chat_id = ANY($1::uuid[])", batch)
            await conn.execute("DELETE FROM chats WHERE id = ANY($1::uuid[])", batch)
        for batch in chunks(user_ids, 5000):
            # user_roles удалится каскадом (ON DELETE CASCADE), chat_members уже удалены выше
            await conn.execute("DELETE FROM users WHERE id = ANY($1::bigint[])", batch)

    path.unlink()
    print("[cleanup] готово")


# ─── main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = parse_args()
    conn = await connect()
    try:
        if args.cleanup:
            await cleanup(conn, args.manifest_out)
            return

        rng = random.Random()

        user_ids = await seed_users(conn, args.tag, args.users, args.batch_size)

        direct = await seed_direct_chats(conn, user_ids, args.direct_chats, args.batch_size, rng)

        group = await seed_chats(
            conn, user_ids, "group", args.group_chats,
            args.group_min_size, args.group_max_size,
            CHAT_ROLE_OWNER, CHAT_ROLE_MEMBER, args.batch_size, rng,
        )

        supergroup = await seed_chats(
            conn, user_ids, "supergroup", args.supergroups,
            args.supergroup_min_size, args.supergroup_max_size,
            CHAT_ROLE_OWNER, CHAT_ROLE_MEMBER, args.batch_size, rng,
        )

        channel = await seed_chats(
            conn, user_ids, "channel", args.channels,
            args.channel_min_size, args.channel_max_size,
            CHAT_ROLE_OWNER, CHAT_ROLE_VIEWER, args.batch_size, rng,
        )

        write_manifest(args.manifest_out, args.tag, user_ids, direct, group, supergroup, channel)

        print(
            f"\n[seed] готово: {len(user_ids)} пользователей, "
            f"{len(direct)} direct, {len(group)} group, "
            f"{len(supergroup)} supergroup, {len(channel)} channel"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
