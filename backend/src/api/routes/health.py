"""Health check endpoints."""

from fastapi import APIRouter

from src.core.registry import datasources, llm_providers

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {"status": "ok"}


@router.get("/health/detailed")
async def detailed_health_check() -> dict:
    """Detailed health check with component status."""
    status = {
        "status": "ok",
        "components": {},
    }

    # Check data source plugins
    try:
        plugin_instances = datasources.list_instances()
        if plugin_instances:
            plugin = datasources.get_instance(plugin_instances[0])
            is_healthy = await plugin.health_check()
            status["components"]["datasource"] = "ok" if is_healthy else "error"
        else:
            status["components"]["datasource"] = "not_configured"
    except Exception as e:
        status["components"]["datasource"] = f"error: {e}"
        status["status"] = "degraded"

    # Check LLM provider
    try:
        if llm_providers.has_instance("default"):
            provider = llm_providers.get_instance("default")
            is_healthy = await provider.health_check()
            status["components"]["llm"] = "ok" if is_healthy else "error"
        else:
            status["components"]["llm"] = "not_configured"
    except Exception as e:
        status["components"]["llm"] = f"error: {e}"
        status["status"] = "degraded"

    return status
