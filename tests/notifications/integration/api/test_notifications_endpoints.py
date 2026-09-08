import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from app.notifications.models.notification import NotificationType
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestNotificationListEndpoints:

    async def test_list_returns_only_own_notifications(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id))
        await persist_notifications(3, user_id=6001)

        response = await client.get(
            api_path("notifications/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {item["user_id"] for item in body["items"]} == {int(user_jwt.id)}

    async def test_list_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get(api_path("notifications/"))
        assert response.status_code in (401, 403)

    async def test_list_is_paginated(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(5, user_id=int(user_jwt.id))
        headers = create_auth_headers(user_jwt)

        first = await client.get(
            api_path("notifications/"), params={"page": 1, "page_size": 2}, headers=headers
        )
        second = await client.get(
            api_path("notifications/"), params={"page": 2, "page_size": 2}, headers=headers
        )

        assert first.status_code == second.status_code == 200
        assert first.json()["total"] == 5
        assert len(first.json()["items"]) == 2

        ids_first = {i["id"] for i in first.json()["items"]}
        ids_second = {i["id"] for i in second.json()["items"]}
        assert ids_first.isdisjoint(ids_second)

    async def test_page_size_over_the_limit_is_rejected(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.get(
            api_path("notifications/"),
            params={"page_size": 1000},
            headers=create_auth_headers(user_jwt),
        )
        assert response.status_code == 422

    async def test_is_read_filter_narrows_the_list(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id), is_read=False)
        await persist_notifications(3, user_id=int(user_jwt.id), is_read=True)
        headers = create_auth_headers(user_jwt)

        unread = await client.get(
            api_path("notifications/"), params={"is_read": "false"}, headers=headers
        )
        read = await client.get(
            api_path("notifications/"), params={"is_read": "true"}, headers=headers
        )

        assert unread.json()["total"] == 2
        assert read.json()["total"] == 3

    async def test_unread_count_matches_the_list(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(4, user_id=int(user_jwt.id), is_read=False)
        await persist_notifications(1, user_id=int(user_jwt.id), is_read=True)

        response = await client.get(
            api_path("notifications/unread_count/"),
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        assert response.json()["unread_count"] == 4

    async def test_unread_count_is_isolated_between_users(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(3, user_id=int(user_jwt.id))
        other = make_user_jwt(id="6002")
        await persist_notifications(1, user_id=6002)

        mine = await client.get(
            api_path("notifications/unread_count/"), headers=create_auth_headers(user_jwt)
        )
        theirs = await client.get(
            api_path("notifications/unread_count/"), headers=create_auth_headers(other)
        )

        assert mine.json()["unread_count"] == 3
        assert theirs.json()["unread_count"] == 1


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestNotificationReadEndpoints:

    async def test_mark_read_updates_the_notification(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        (notification,) = await persist_notifications(1, user_id=int(user_jwt.id))
        headers = create_auth_headers(user_jwt)

        response = await client.patch(
            api_path(f"notifications/{notification.id}/read/"),
            json={"is_read": True},
            headers=headers,
        )
        assert response.status_code == 200

        listed = await client.get(api_path("notifications/"), headers=headers)
        assert listed.json()["items"][0]["is_read"] is True

    async def test_mark_read_on_a_foreign_notification_is_forbidden(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        (notification,) = await persist_notifications(1, user_id=6003)

        response = await client.patch(
            api_path(f"notifications/{notification.id}/read/"),
            json={"is_read": True},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOTIFICATION_ACCESS_DENIED"

    async def test_mark_read_on_a_missing_notification_is_404(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.patch(
            api_path("notifications/9999999/read/"),
            json={"is_read": True},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_NOTIFICATION"

    async def test_read_all_clears_the_unread_counter(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(4, user_id=int(user_jwt.id))
        headers = create_auth_headers(user_jwt)

        response = await client.patch(api_path("notifications/read_all/"), headers=headers)
        assert response.status_code == 200

        count = await client.get(api_path("notifications/unread_count/"), headers=headers)
        assert count.json()["unread_count"] == 0


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestNotificationCacheFreshness:
    async def test_unread_count_reflects_mark_read(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        notifications = await persist_notifications(3, user_id=int(user_jwt.id))
        headers = create_auth_headers(user_jwt)

        warmed = await client.get(api_path("notifications/unread_count/"), headers=headers)
        assert warmed.json()["unread_count"] == 3

        marked = await client.patch(
            api_path(f"notifications/{notifications[0].id}/read/"),
            json={"is_read": True},
            headers=headers,
        )
        assert marked.status_code == 200

        after = await client.get(api_path("notifications/unread_count/"), headers=headers)
        assert after.json()["unread_count"] == 2

    async def test_list_reflects_read_all(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id))
        headers = create_auth_headers(user_jwt)

        warmed = await client.get(
            api_path("notifications/"), params={"is_read": "false"}, headers=headers
        )
        assert warmed.json()["total"] == 2

        await client.patch(api_path("notifications/read_all/"), headers=headers)

        after = await client.get(
            api_path("notifications/"), params={"is_read": "false"}, headers=headers
        )
        assert after.json()["total"] == 0

    async def test_cached_list_is_not_shared_between_users(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
        persist_notifications,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id))
        other = make_user_jwt(id="6004")
        await persist_notifications(1, user_id=6004)

        mine = await client.get(
            api_path("notifications/"), headers=create_auth_headers(user_jwt)
        )
        theirs = await client.get(
            api_path("notifications/"), headers=create_auth_headers(other)
        )

        assert mine.json()["total"] == 2
        assert theirs.json()["total"] == 1


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestDeviceEndpoint:

    async def test_device_is_registered(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        device_repository,
    ) -> None:
        response = await client.post(
            api_path("devices/"),
            json={
                "platform": "ANDROID",
                "token": "http-fcm-token",
                "device_name": "Pixel",
            },
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 201
        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert [d.token for d in devices] == ["http-fcm-token"]

    async def test_duplicate_registration_is_a_client_error(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        device_repository,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        payload = {
            "platform": "IOS",
            "token": "http-duplicate-token",
            "device_name": "iPhone",
        }

        first = await client.post(api_path("devices/"), json=payload, headers=headers)
        assert first.status_code == 201

        second = await client.post(api_path("devices/"), json=payload, headers=headers)

        assert second.status_code == 400
        assert second.json()["error"]["code"] == "ALREADY_EXIST_DEVICE_TOKEN"

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert len(devices) == 1

    async def test_unknown_platform_is_rejected(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.post(
            api_path("devices/"),
            json={"platform": "SYMBIAN", "token": "t", "device_name": "d"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 422

    async def test_device_registration_requires_authentication(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            api_path("devices/"),
            json={"platform": "WEB", "token": "t", "device_name": "d"},
        )

        assert response.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestNotificationTypesAreExposed:

    @pytest.mark.parametrize(
        "notification_type",
        [NotificationType.SYSTEM, NotificationType.CHAT, NotificationType.PROJECT],
    )
    async def test_type_survives_the_round_trip(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persist_notifications,
        notification_type: NotificationType,
    ) -> None:
        await persist_notifications(
            1, user_id=int(user_jwt.id), type=notification_type
        )

        response = await client.get(
            api_path("notifications/"), headers=create_auth_headers(user_jwt)
        )

        assert response.json()["items"][0]["type"] == notification_type.value
