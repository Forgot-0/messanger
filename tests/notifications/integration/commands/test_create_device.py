# ruff: noqa: S105, S106 - это FCM-регистрации, а не пароли.

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.services.auth.dto import UserJWTData
from app.notifications.commands.devices.create import (
    CreateUserDeviceCommand,
    CreateUserDeviceCommandHandler,
)
from app.notifications.exceptions import AlreadyExistDeviceTokennError
from app.notifications.models.device import PlatformEnum
from app.notifications.repositories.devices import DeviceRepository


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestCreateUserDeviceCommand:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> CreateUserDeviceCommandHandler:
        return await request_container.get(CreateUserDeviceCommandHandler)

    async def test_device_is_bound_to_the_user_from_the_token(
        self,
        handler: CreateUserDeviceCommandHandler,
        device_repository: DeviceRepository,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            CreateUserDeviceCommand(
                token="fcm-token-1",
                platform=PlatformEnum.android,
                device_name="Pixel 8",
                user_jwt_data=user_jwt,
            )
        )

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert len(devices) == 1
        assert devices[0].token == "fcm-token-1"
        assert devices[0].platform == PlatformEnum.android
        assert devices[0].device_name == "Pixel 8"
        assert devices[0].is_active is True

    @pytest.mark.parametrize(
        "platform", [PlatformEnum.android, PlatformEnum.ios, PlatformEnum.web]
    )
    async def test_every_platform_is_accepted(
        self,
        handler: CreateUserDeviceCommandHandler,
        device_repository: DeviceRepository,
        user_jwt: UserJWTData,
        platform: PlatformEnum,
    ) -> None:
        await handler.handle(
            CreateUserDeviceCommand(
                token=f"token-{platform.value}",
                platform=platform,
                device_name="Устройство",
                user_jwt_data=user_jwt,
            )
        )

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert devices[0].platform == platform

    async def test_user_can_register_several_devices(
        self,
        handler: CreateUserDeviceCommandHandler,
        device_repository: DeviceRepository,
        user_jwt: UserJWTData,
    ) -> None:
        for i in range(3):
            await handler.handle(
                CreateUserDeviceCommand(
                    token=f"fcm-token-{i}",
                    platform=PlatformEnum.web,
                    device_name=f"Браузер {i}",
                    user_jwt_data=user_jwt,
                )
            )

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert {d.token for d in devices} == {"fcm-token-0", "fcm-token-1", "fcm-token-2"}

    async def test_duplicate_token_is_rejected_by_the_handler(
        self,
        handler: CreateUserDeviceCommandHandler,
        device_repository: DeviceRepository,
        user_jwt: UserJWTData,
    ) -> None:
        command = CreateUserDeviceCommand(
            token="fcm-duplicate",
            platform=PlatformEnum.ios,
            device_name="iPhone",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command)

        with pytest.raises(AlreadyExistDeviceTokennError):
            await handler.handle(command)

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert len(devices) == 1

    async def test_deactivated_token_is_reactivated_instead_of_duplicated(
        self,
        handler: CreateUserDeviceCommandHandler,
        device_repository: DeviceRepository,
        db_session: AsyncSession,
        user_jwt: UserJWTData,
    ) -> None:
        command = CreateUserDeviceCommand(
            token="fcm-revived",
            platform=PlatformEnum.web,
            device_name="Браузер",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command)

        await device_repository.deactivate_tokens(["fcm-revived"])
        await db_session.commit()
        assert await device_repository.get_active_by_user_id(int(user_jwt.id)) == []

        await handler.handle(command)

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert len(devices) == 1
        assert devices[0].token == "fcm-revived"
        assert devices[0].is_active is True

    async def test_reactivation_keeps_the_original_row(
        self,
        handler: CreateUserDeviceCommandHandler,
        device_repository: DeviceRepository,
        db_session: AsyncSession,
        user_jwt: UserJWTData,
    ) -> None:
        command = CreateUserDeviceCommand(
            token="fcm-same-row",
            platform=PlatformEnum.ios,
            device_name="iPhone",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command)
        original_id = (await device_repository.get_active_by_user_id(int(user_jwt.id)))[0].id

        await device_repository.deactivate_tokens(["fcm-same-row"])
        await db_session.commit()
        await handler.handle(command)

        devices = await device_repository.get_active_by_user_id(int(user_jwt.id))
        assert [d.id for d in devices] == [original_id]

