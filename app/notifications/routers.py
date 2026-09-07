from fastapi import APIRouter

from app.notifications.routes.v1 import devices, notifications

router_v1 = APIRouter()
router_v1.include_router(devices.router, prefix="/devices", tags=["notifications"])
router_v1.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
