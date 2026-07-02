"""Generic plugin HTTP routing and guards."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from src.api.dependencies import get_current_user
from src.core.protocols import BasePlugin, HttpRoutablePlugin

logger = logging.getLogger(__name__)

PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
MAX_PLUGIN_RESPONSE_BYTES = 2_000_000


def _is_valid_plugin_id(plugin_id: str) -> bool:
    return bool(PLUGIN_ID_PATTERN.fullmatch(plugin_id))


def _get_plugin_auth_mode(plugin: HttpRoutablePlugin) -> str:
    auth_mode_getter = getattr(plugin, "get_api_auth_mode", None)
    if callable(auth_mode_getter):
        try:
            mode = auth_mode_getter()
            if mode in {"authenticated", "public"}:
                return mode
        except Exception as exc:
            logger.warning("Failed to read plugin auth mode for '%s': %s", plugin.name, exc)
    return "authenticated"


def mount_plugin_http_routers(app: FastAPI, plugins: dict[str, BasePlugin]) -> list[str]:
    """Mount plugin routers under /api/plugins/{plugin_id}."""
    mounted: list[str] = []

    for plugin_id, plugin in plugins.items():
        if not isinstance(plugin, HttpRoutablePlugin):
            continue
        if not _is_valid_plugin_id(plugin_id):
            logger.warning("Skipping plugin router for invalid plugin id: '%s'", plugin_id)
            continue

        try:
            router = plugin.get_api_router()
            if not isinstance(router, APIRouter):
                logger.warning("Plugin '%s' returned non-APIRouter object", plugin_id)
                continue
        except Exception as exc:
            logger.warning("Failed to get API router for plugin '%s': %s", plugin_id, exc)
            continue

        auth_mode = _get_plugin_auth_mode(plugin)
        dependencies = [] if auth_mode == "public" else [Depends(get_current_user)]

        app.include_router(
            router,
            prefix=f"/api/plugins/{plugin_id}",
            tags=[f"plugin:{plugin_id}"],
            dependencies=dependencies,
        )
        mounted.append(plugin_id)
        logger.info("Mounted HTTP router for plugin '%s' (auth=%s)", plugin_id, auth_mode)

    return mounted


def register_plugin_payload_guard(app: FastAPI) -> None:
    """Limit payload size returned by plugin endpoints."""

    @app.middleware("http")
    async def plugin_payload_guard(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        if not request.url.path.startswith("/api/plugins/"):
            return response

        content_length_header = response.headers.get("content-length")
        if content_length_header and content_length_header.isdigit():
            if int(content_length_header) > MAX_PLUGIN_RESPONSE_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Plugin response exceeds maximum allowed size."},
                )

        body = getattr(response, "body", None)
        if isinstance(body, bytes) and len(body) > MAX_PLUGIN_RESPONSE_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Plugin response exceeds maximum allowed size."},
            )
        return response
