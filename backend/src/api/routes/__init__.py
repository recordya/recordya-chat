"""API Routes."""

from fastapi import APIRouter

from .auth import router as auth_router
from .chat import router as chat_router
from .chats import router as chats_router
from .config import router as config_router
from .datasources import router as datasources_router
from .health import router as health_router
from .views import router as views_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(chat_router, prefix="/api", tags=["chat"])
router.include_router(chats_router, prefix="/api", tags=["chats"])
router.include_router(config_router, prefix="/api/config", tags=["config"])
router.include_router(datasources_router, prefix="/api/datasources", tags=["datasources"])
router.include_router(views_router, prefix="/api/views", tags=["views"])
