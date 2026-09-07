"""
Загрузка манифеста, который пишет loadtests/seed.py: список посеянных
пользователей и чатов (direct/group/supergroup/channel) с их участниками.

Locust-сценарии не ходят в БД напрямую — они читают этот JSON-файл один раз
при старте (--processes/воркеры каждый читает свою копию файла, файл только
на чтение) и дальше работают с ним в памяти.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ChatKind = Literal["direct", "group", "supergroup", "channel"]


@dataclass(frozen=True, slots=True)
class ManifestUser:
    id: int
    username: str


@dataclass(frozen=True, slots=True)
class ManifestChat:
    id: str
    kind: ChatKind
    owner_id: int
    # Для group/supergroup: все участники могут писать (role_id=5, MEMBER).
    # Для channel: писать может только owner/staff (role_id=1/2/3) — обычные
    # участники сидят с role_id=6 (VIEWER, message:send=False), поэтому для
    # канала важно не пытаться слать сообщения от лица случайного member_ids.
    member_ids: list[int] = field(default_factory=list)

    @property
    def can_any_member_write(self) -> bool:
        return self.kind != "channel"


@dataclass(frozen=True, slots=True)
class Manifest:
    tag: str
    users_by_id: dict[int, ManifestUser]
    chats_by_kind: dict[ChatKind, list[ManifestChat]]

    @property
    def all_users(self) -> list[ManifestUser]:
        return list(self.users_by_id.values())

    def random_chat(self, kind: ChatKind, rng: random.Random) -> ManifestChat:
        chats = self.chats_by_kind.get(kind) or []
        if not chats:
            raise ValueError(
                f"В манифесте нет чатов типа {kind!r}. Перезапустите loadtests/seed.py "
                f"с ненулевым количеством чатов этого типа."
            )
        return rng.choice(chats)

    def user(self, user_id: int) -> ManifestUser:
        return self.users_by_id[user_id]


def load_manifest(path: str) -> Manifest:
    raw = json.loads(Path(path).read_text())

    users_by_id = {
        int(u["id"]): ManifestUser(id=int(u["id"]), username=u["username"])
        for u in raw["users"]
    }

    chats_by_kind: dict[ChatKind, list[ManifestChat]] = {"direct": [], "group": [], "supergroup": [], "channel": []}
    for kind in chats_by_kind:
        for c in raw["chats"].get(kind, []):
            chats_by_kind[kind].append(
                ManifestChat(
                    id=c["id"],
                    kind=kind,
                    owner_id=int(c["owner_id"]),
                    member_ids=[int(m) for m in c["member_ids"]],
                )
            )

    return Manifest(tag=raw["tag"], users_by_id=users_by_id, chats_by_kind=chats_by_kind)
