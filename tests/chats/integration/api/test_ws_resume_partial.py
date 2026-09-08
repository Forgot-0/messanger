import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload, send_text_payload
from tests.chats.integration.ws_asgi_client import AsyncASGIWebSocketSession
from tests.support.http import api_path


async def _collect_until_quiet(
    ws: AsyncASGIWebSocketSession,
    *,
    expected: int,
    timeout: float = 5.0,
) -> list[dict]:
    frames: list[dict] = []
    while len(frames) < expected:
        try:
            frames.append(await ws.recv_event(timeout=timeout))
        except TimeoutError:
            break
    return frames


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestResumeWithMixedCursors:

    async def test_foreign_chat_does_not_abort_the_rest_of_resume(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        stranger = make_user_jwt(id="71001", username="resume_stranger")
        foreign = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Чужой чат", member_ids=[71001]),
            headers=create_auth_headers(stranger),
        )
        assert foreign.status_code == 201
        foreign_id = foreign.json()["id"]

        own = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Свой чат"),
            headers=headers,
        )
        assert own.status_code == 201
        own_id = own.json()["id"]

        sent = await client.post(
            api_path(f"chats/{own_id}/messages/"),
            json=send_text_payload("пропущенное сообщение"),
            headers=headers,
        )
        assert sent.status_code == 201
        missed_seq = sent.json()["seq"]

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            assert (await ws.recv_event())["type"] == "ws.ready"

            await ws.send_json({
                "op": "resume",
                "cursors": {foreign_id: 0, own_id: 0},
            })

            frames = await _collect_until_quiet(ws, expected=3)

        by_type: dict[str, list[dict]] = {}
        for frame in frames:
            by_type.setdefault(frame["type"], []).append(frame)

        errors = by_type.get("ws.error", [])
        assert len(errors) == 1
        assert errors[0]["code"] == "NOT_CHAT_MEMBER"

        subscribed = by_type.get("ws.subscribed", [])
        assert [s["chat_id"] for s in subscribed] == [own_id]

        history = by_type.get("ws.history", [])
        assert len(history) == 1
        assert history[0]["chat_id"] == own_id
        assert missed_seq in {m["seq"] for m in history[0]["payload"]["messages"]}

    async def test_every_accessible_chat_in_the_cursor_map_is_restored(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        chat_ids = []
        for i in range(3):
            created = await client.post(
                api_path("chats/"),
                json=group_chat_payload(name=f"Resume all {i}"),
                headers=headers,
            )
            assert created.status_code == 201
            chat_ids.append(created.json()["id"])

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()
            await ws.send_json({
                "op": "resume",
                "cursors": dict.fromkeys(chat_ids, 0),
            })

            frames = await _collect_until_quiet(ws, expected=6)

        subscribed = {f["chat_id"] for f in frames if f["type"] == "ws.subscribed"}
        assert subscribed == set(chat_ids)

    async def test_cursor_map_over_the_limit_is_reported_to_the_client(
        self,
        app,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        from uuid import uuid4

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()

            await ws.send_json({
                "op": "resume",
                "cursors": {str(uuid4()): 0 for _ in range(21)},
            })

            error = await ws.recv_event()
            assert error["type"] == "ws.error"
            assert error["code"] == "MAX_LIMIT_CURSOR"
