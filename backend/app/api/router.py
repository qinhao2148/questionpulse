from fastapi import APIRouter

from app.api.routes.classroom import router as classroom_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(classroom_router, tags=["classroom"])
