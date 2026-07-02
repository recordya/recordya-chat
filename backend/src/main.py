"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.plugin_http import mount_plugin_http_routers, register_plugin_payload_guard
from src.api.routes import router
from src.core.config import settings
from src.core.discovery import PluginDiscovery, set_discovery
from src.core.langfuse import shutdown_langfuse
from src.core.protocols import ViewPlugin
from src.core.registry import datasources, llm_providers, view_plugins
from src.db.app_database import close_db, init_db
from src.llm.openai import OpenAIProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info("Starting up...")

    # Initialize application database
    await init_db()
    logger.info("Application database initialized")

    # Initialize LLM provider
    llm_provider = OpenAIProvider(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        name="default",
    )
    llm_providers.register_instance("default", llm_provider)
    logger.info(f"LLM provider registered: {llm_provider.name}")

    # Discover and load plugins from the sibling plugins/ folder (next to the repo root)
    # Supports both unified (plugins/x/backend/) and legacy (backend/plugins/x/) structures.
    # The sibling path resolves the same way locally (../plugins next to core/) and in
    # Docker Compose (/plugins mount); production images fall back to /app/plugins.
    root_plugins_dir = Path(__file__).parent.parent.parent.parent / "plugins"
    legacy_plugins_dir = Path(__file__).parent.parent / settings.PLUGINS_DIR
    
    # Prefer root-level plugins folder if it exists
    plugins_dir = root_plugins_dir if root_plugins_dir.exists() else legacy_plugins_dir
    discovery = PluginDiscovery(plugins_dir=plugins_dir)
    set_discovery(discovery)

    loaded_plugins = await discovery.discover_and_load()
    logger.info(f"Loaded {len(loaded_plugins)} plugins: {list(loaded_plugins.keys())}")

    # Register loaded plugins in appropriate registries based on type
    for name, plugin in loaded_plugins.items():
        if isinstance(plugin, ViewPlugin):
            view_plugins.register_instance(name, plugin)
        else:
            datasources.register_instance(name, plugin)

    # Mount optional plugin-owned HTTP routers (from BasePlugin instances)
    mounted_routers = mount_plugin_http_routers(app, loaded_plugins)
    if mounted_routers:
        logger.info("Mounted plugin HTTP routers: %s", mounted_routers)

    # Mount HTTP-only routers (non-BasePlugin, e.g. webhooks)
    from src.core.registry import http_routers
    http_only_plugins = http_routers.get_all_instances()
    if http_only_plugins:
        mounted_http_only = mount_plugin_http_routers(app, http_only_plugins)
        if mounted_http_only:
            logger.info("Mounted HTTP-only routers: %s", mounted_http_only)

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Flush Langfuse traces
    shutdown_langfuse()
    logger.info("Langfuse flushed")

    # Shutdown plugins
    await discovery.shutdown_all()
    logger.info("Plugins shut down")

    # Close application database
    await close_db()
    logger.info("Application database closed")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Knowledge Base API",
        description="Backend API for data analysis with plugin architecture",
        version="0.2.0",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(router)
    register_plugin_payload_guard(app)

    return app


# Application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
