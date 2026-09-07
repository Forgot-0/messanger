from pydantic import BaseModel

from app.notifications.models.device import PlatformEnum


class CreateUserDeviceRequest(BaseModel):
    platform: PlatformEnum
    token: str
    device_name: str

