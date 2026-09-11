from fastapi import APIRouter

from app.profiles.routes.v1 import contacts, profile

router_v1 = APIRouter()
router_v1.include_router(profile.router, prefix="/profiles", tags=["profiles"])
router_v1.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
