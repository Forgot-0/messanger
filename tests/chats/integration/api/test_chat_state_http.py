from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from app.chats.config import chat_config
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from tests.support.http import api_path


async def _patch_state(
    client: AsyncClient,
    chat_id: str,
    headers: dict[str, str],
    payload: dict,
) -> Response:
    return await client.patch(
        api_path(f"chats/{chat_id}/state/"), json=payload, headers=headers
    )


async def _listed_ids(client: AsyncClient, headers: dict[str, str], **params) -> list[str]:
    response = await client.get(api_path("chats/"), params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [chat["id"] for chat in response.json()["chats"]]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatStateHttpEndpoints:
    async def test_absent_field_keeps_value_and_null_clears_it(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        create_group_chat,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat = await create_group_chat(members=[2], name="State chat")
        chat_id = str(chat.id)

        pinned = await _patch_state(client, chat_id, headers, {"pinned": True})
        assert pinned.status_code == 200, pinned.text
        body = pinned.json()
        assert body["chat_id"] == chat_id
        assert body["is_pinned"] is True
        assert body["pinned_at"] is not None
        assert body["is_archived"] is False
        assert body["draft"] is None

        # Поля нет в теле → не трогаем: пин обязан пережить правку черновика.
        drafted = await _patch_state(client, chat_id, headers, {"draft": "  недописанное  "})
        assert drafted.status_code == 200
        body = drafted.json()
        assert body["draft"] == "недописанное"
        assert body["draft_updated_at"] is not None
        assert body["is_pinned"] is True

        # Поле передано как null → очищаем.
        cleared = await _patch_state(client, chat_id, headers, {"draft": None})
        assert cleared.status_code == 200
        body = cleared.json()
        assert body["draft"] is None
        assert body["draft_updated_at"] is None
        assert body["is_pinned"] is True

        unpinned = await _patch_state(client, chat_id, headers, {"pinned": None})
        assert unpinned.status_code == 200
        body = unpinned.json()
        assert body["is_pinned"] is False
        assert body["pinned_at"] is None

    async def test_notifications_mute_is_derived_and_visible_in_list(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        create_group_chat,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat = await create_group_chat(members=[2], name="Muted chat")
        chat_id = str(chat.id)
        muted_until = now_utc() + timedelta(hours=1)

        muted = await _patch_state(
            client, chat_id, headers, {"notifications_muted_until": muted_until.isoformat()}
        )
        assert muted.status_code == 200
        assert muted.json()["is_muted_by_me"] is True

        response = await client.get(api_path("chats/"), headers=headers)
        listed = next(item for item in response.json()["chats"] if item["id"] == chat_id)
        assert listed["is_muted_by_me"] is True
        assert listed["notifications_muted_until"] is not None
        # Мьют уведомлений не имеет отношения к модераторскому мьюту участника.
        assert listed["me"]["is_muted"] is False

        unmuted = await _patch_state(client, chat_id, headers, {"notifications_muted_until": None})
        assert unmuted.status_code == 200
        assert unmuted.json()["is_muted_by_me"] is False
        assert unmuted.json()["notifications_muted_until"] is None

    async def test_pin_over_the_limit_is_rejected(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        create_group_chat,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chats = [
            await create_group_chat(members=[2], name=f"Pinned {index}")
            for index in range(chat_config.MAX_PINNED_CHATS + 1)
        ]

        for chat in chats[:chat_config.MAX_PINNED_CHATS]:
            response = await _patch_state(client, str(chat.id), headers, {"pinned": True})
            assert response.status_code == 200, response.text

        over_limit = await _patch_state(client, str(chats[-1].id), headers, {"pinned": True})
        assert over_limit.status_code == 400
        error = over_limit.json()["error"]
        assert error["code"] == "PINNED_CHATS_LIMIT_EXCEEDED"
        assert error["detail"] == {"limit": chat_config.MAX_PINNED_CHATS}

        # Повторный пин уже запиненного чата лимит не трогает.
        repeat = await _patch_state(client, str(chats[0].id), headers, {"pinned": True})
        assert repeat.status_code == 200

    async def test_pinned_chats_lead_the_first_page_in_pinned_at_desc_order(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        create_group_chat,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chats = [await create_group_chat(members=[2], name=f"Chat {index}") for index in range(3)]
        first_pinned, second_pinned = chats[0], chats[1]

        assert (await _patch_state(client, str(first_pinned.id), headers, {"pinned": True})).status_code == 200
        assert (await _patch_state(client, str(second_pinned.id), headers, {"pinned": True})).status_code == 200

        listed = await _listed_ids(client, headers)

        # Позже запиненный идёт первым: порядок пинов — pinned_at DESC.
        assert listed[:2] == [str(second_pinned.id), str(first_pinned.id)]
        # И в keyset-теле их уже нет — каждый чат в ответе ровно один раз.
        assert len(listed) == len(set(listed))
        assert str(chats[2].id) in listed

    async def test_archived_chats_are_hidden_until_asked_for(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        create_group_chat,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        active = await create_group_chat(members=[2], name="Active")
        archived = await create_group_chat(members=[2], name="Archived")

        assert (await _patch_state(client, str(archived.id), headers, {"archived": True})).status_code == 200

        default_page = await _listed_ids(client, headers)
        assert str(active.id) in default_page
        assert str(archived.id) not in default_page

        archived_page = await _listed_ids(client, headers, archived="true")
        assert archived_page == [str(archived.id)]

        # Пины архива живут в своём наборе и на общий список не влияют.
        assert (await _patch_state(client, str(archived.id), headers, {"pinned": True})).status_code == 200
        assert await _listed_ids(client, headers, archived="true") == [str(archived.id)]
        assert str(archived.id) not in await _listed_ids(client, headers)

    async def test_state_of_a_chat_without_membership_is_not_found(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
        create_group_chat,
    ) -> None:
        chat = await create_group_chat(members=[2], name="Someone else's chat")
        stranger = make_user_jwt(id="77777", username="stranger77777")

        response = await _patch_state(
            client, str(chat.id), create_auth_headers(stranger), {"pinned": True}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_CHAT"

        missing = await _patch_state(
            client, str(uuid4()), create_auth_headers(user_jwt), {"pinned": True}
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NOT_FOUND_CHAT"
