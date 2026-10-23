from fastapi import APIRouter

from app.api.routes import checks, clusters, questions, reports, sessions
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(sessions.router, tags=["classroom"])
api_router.include_router(questions.router, tags=["classroom"])
api_router.include_router(clusters.router, tags=["classroom"])
api_router.include_router(reports.router, tags=["classroom"])
api_router.include_router(checks.router, tags=["classroom"])
