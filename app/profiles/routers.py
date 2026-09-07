from fastapi import APIRouter

from app.profiles.routes.v1 import profile

router_v1 = APIRouter()
router_v1.include_router(profile.router, prefix="/profiles", tags=["profiles"])

