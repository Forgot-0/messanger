from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.chats.config import chat_config
from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload, send_text_payload
from tests.support.http import api_path


async def _chat_with_message(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Reactions chat",
    member_ids: list[int] | None = None,
) -> tuple[str, str]:
    created = await client.post(
        api_path("chats/"),
        json=group_chat_payload(name=name, member_ids=member_ids),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    chat_id = created.json()["id"]

    sent = await client.post(
        api_path(f"chats/{chat_id}/messages/"),
        json=send_text_payload("на что реагируем"),
        headers=headers,
    )
    assert sent.status_code == 201, sent.text
    return chat_id, sent.json()["id"]


def _reactions_path(chat_id: str, message_id: str, suffix: str = "") -> str:
    return api_path(f"chats/{chat_id}/messages/{message_id}/reactions/{suffix}")


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSingleReactionEndpoints:

    async def test_put_adds_a_reaction_visible_in_get(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        put = await client.put(_reactions_path(chat_id, message_id, "👍/"), headers=headers)
        assert put.status_code == 204

        listed = await client.get(_reactions_path(chat_id, message_id), headers=headers)
        assert listed.status_code == 200
        groups = listed.json()["groups"]
        assert [(g["emoji"], g["count"]) for g in groups] == [("👍", 1)]
        assert groups[0]["reacted_by_me"] is True

    async def test_delete_removes_the_reaction(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)
        await client.put(_reactions_path(chat_id, message_id, "👍/"), headers=headers)

        removed = await client.delete(
            _reactions_path(chat_id, message_id, "👍/"), headers=headers
        )
        assert removed.status_code == 204

        listed = await client.get(_reactions_path(chat_id, message_id), headers=headers)
        assert listed.json()["groups"] == []

    async def test_multibyte_emoji_survives_the_url(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        put = await client.put(_reactions_path(chat_id, message_id, "❤️/"), headers=headers)
        assert put.status_code == 204

        listed = await client.get(_reactions_path(chat_id, message_id), headers=headers)
        assert [g["emoji"] for g in listed.json()["groups"]] == ["❤️"]

    async def test_repeated_put_does_not_double_the_count(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        for _ in range(3):
            response = await client.put(
                _reactions_path(chat_id, message_id, "🔥/"), headers=headers
            )
            assert response.status_code == 204

        listed = await client.get(_reactions_path(chat_id, message_id), headers=headers)
        assert [(g["emoji"], g["count"]) for g in listed.json()["groups"]] == [("🔥", 1)]

    async def test_unknown_emoji_is_a_client_error(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        response = await client.put(
            _reactions_path(chat_id, message_id, "notanemoji/"), headers=headers
        )

        assert response.status_code < 500
        assert response.json()["error"]["code"] == "INVALID_REACTION"

    async def test_emoji_longer_than_the_limit_is_rejected_by_the_schema(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        response = await client.put(
            _reactions_path(
                chat_id, message_id, "x" * (chat_config.MAX_REACTION_LENGTH + 1) + "/"
            ),
            headers=headers,
        )

        assert response.status_code == 422

    async def test_per_user_limit_is_enforced_over_http(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        for emoji in ("👍", "🔥", "❤️"):
            response = await client.put(
                _reactions_path(chat_id, message_id, f"{emoji}/"), headers=headers
            )
            assert response.status_code == 204

        overflow = await client.put(
            _reactions_path(chat_id, message_id, "🎉/"), headers=headers
        )

        assert overflow.status_code < 500
        assert overflow.json()["error"]["code"] == "TOO_MANY_REACTIONS"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestBulkReactionEndpoints:

    async def test_put_replaces_the_whole_set(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        first = await client.put(
            _reactions_path(chat_id, message_id),
            json={"reactions": ["👍", "🔥"]},
            headers=headers,
        )
        assert first.status_code == 204

        second = await client.put(
            _reactions_path(chat_id, message_id),
            json={"reactions": ["❤️"]},
            headers=headers,
        )
        assert second.status_code == 204

        listed = await client.get(_reactions_path(chat_id, message_id), headers=headers)
        assert [g["emoji"] for g in listed.json()["groups"]] == ["❤️"]

    async def test_clear_reactions_removes_everything_of_this_user(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)
        await client.put(
            _reactions_path(chat_id, message_id),
            json={"reactions": ["👍", "🔥"]},
            headers=headers,
        )

        cleared = await client.delete(_reactions_path(chat_id, message_id), headers=headers)
        assert cleared.status_code == 204

        listed = await client.get(_reactions_path(chat_id, message_id), headers=headers)
        assert listed.json()["groups"] == []

    async def test_clear_keeps_reactions_of_other_members(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        peer = make_user_jwt(id="60101", username="reactpeer")
        peer_headers = create_auth_headers(peer)

        chat_id, message_id = await _chat_with_message(
            client, owner_headers, member_ids=[1, 60_101]
        )

        await client.put(_reactions_path(chat_id, message_id, "👍/"), headers=owner_headers)
        await client.put(_reactions_path(chat_id, message_id, "👍/"), headers=peer_headers)

        await client.delete(_reactions_path(chat_id, message_id), headers=owner_headers)

        listed = await client.get(_reactions_path(chat_id, message_id), headers=peer_headers)
        assert [(g["emoji"], g["count"]) for g in listed.json()["groups"]] == [("👍", 1)]

    async def test_bulk_put_over_the_user_limit_is_rejected_by_the_schema(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        response = await client.put(
            _reactions_path(chat_id, message_id),
            json={"reactions": ["👍", "🔥", "❤️", "🎉"]},
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION"

    async def test_bulk_put_with_an_unknown_emoji_is_rejected(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, headers)

        response = await client.put(
            _reactions_path(chat_id, message_id),
            json={"reactions": ["👍", "bogus"]},
            headers=headers,
        )

        assert response.status_code < 500
        assert response.json()["error"]["code"] == "INVALID_REACTION"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestReactionAccessControl:

    async def test_outsider_cannot_read_reactions(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, owner_headers)
        outsider = make_user_jwt(id="60102", username="reactoutsider")

        response = await client.get(
            _reactions_path(chat_id, message_id),
            headers=create_auth_headers(outsider),
        )

        assert response.status_code in (403, 404)

    async def test_outsider_cannot_set_a_reaction(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        chat_id, message_id = await _chat_with_message(client, owner_headers)
        outsider = make_user_jwt(id="60103", username="reactintruder")

        response = await client.put(
            _reactions_path(chat_id, message_id, "👍/"),
            headers=create_auth_headers(outsider),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_CHAT"

    async def test_banned_member_cannot_react(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        target_id = 60_104
        chat_id, message_id = await _chat_with_message(
            client, owner_headers, member_ids=[1, target_id]
        )

        ban = await client.patch(
            api_path(f"chats/{chat_id}/members/{target_id}/ban/"),
            json={"ban": True},
            headers=owner_headers,
        )
        assert ban.status_code == 204

        banned_headers = create_auth_headers(make_user_jwt(id=str(target_id)))
        response = await client.put(
            _reactions_path(chat_id, message_id, "👍/"), headers=banned_headers
        )

        assert response.status_code in (403, 404)

    async def test_reaction_on_a_missing_message_is_404(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id, _ = await _chat_with_message(client, headers)

        response = await client.put(
            _reactions_path(chat_id, str(uuid4()), "👍/"), headers=headers
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_MESSAGE"

    async def test_reaction_endpoints_require_authentication(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        chat_id, message_id = await _chat_with_message(
            client, create_auth_headers(user_jwt)
        )

        response = await client.get(_reactions_path(chat_id, message_id))

        assert response.status_code in (401, 403)
