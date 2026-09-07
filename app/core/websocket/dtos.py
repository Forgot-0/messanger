from typing import Any

from pydantic import BaseModel


class DeliveryData(BaseModel):
    require_subscription: bool
    recipients: list[int]


class DeliveryDTO(BaseModel):
    type: str
    channel: str
    payload: dict[str, Any]
    delivery: DeliveryData
    ts: str
