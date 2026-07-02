"""Tests for generic plugin HTTP routing."""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.api.plugin_http import MAX_PLUGIN_RESPONSE_BYTES, mount_plugin_http_routers, register_plugin_payload_guard
from src.core.protocols import BasePlugin


class BasicPlugin(BasePlugin):
    name = "basic_plugin"
    display_name = "Basic"
    description = "No HTTP router"


class AuthenticatedHttpPlugin(BasePlugin):
    name = "auth_plugin"
    display_name = "AuthPlugin"
    description = "Authenticated endpoint"

    def get_api_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/ping")
        async def ping() -> dict[str, str]:
            return {"status": "ok"}

        return router

    def get_api_auth_mode(self) -> str:
        return "authenticated"


class PublicHttpPlugin(BasePlugin):
    name = "public_plugin"
    display_name = "PublicPlugin"
    description = "Public endpoint"

    def get_api_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/ping")
        async def ping() -> dict[str, str]:
            return {"status": "ok"}

        return router

    def get_api_auth_mode(self) -> str:
        return "public"


class LargePayloadPlugin(BasePlugin):
    name = "large_plugin"
    display_name = "LargePlugin"
    description = "Large payload endpoint"

    def get_api_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/blob")
        async def blob() -> dict[str, str]:
            return {"payload": "x" * (MAX_PLUGIN_RESPONSE_BYTES + 1024)}

        return router

    def get_api_auth_mode(self) -> str:
        return "public"


def _create_app(plugins: dict[str, BasePlugin]) -> FastAPI:
    app = FastAPI()
    mount_plugin_http_routers(app, plugins)
    register_plugin_payload_guard(app)
    return app


def test_non_routable_plugin_is_ignored() -> None:
    app = _create_app({"basic_plugin": BasicPlugin()})
    client = TestClient(app)
    response = client.get("/api/plugins/basic_plugin/ping")
    assert response.status_code == 404


def test_authenticated_plugin_route_requires_auth() -> None:
    app = _create_app({"auth_plugin": AuthenticatedHttpPlugin()})
    client = TestClient(app)
    response = client.get("/api/plugins/auth_plugin/ping")
    assert response.status_code == 401


def test_public_plugin_route_is_accessible() -> None:
    app = _create_app({"public_plugin": PublicHttpPlugin()})
    client = TestClient(app)
    response = client.get("/api/plugins/public_plugin/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_plugin_payload_guard_rejects_large_responses() -> None:
    app = _create_app({"large_plugin": LargePayloadPlugin()})
    client = TestClient(app)
    response = client.get("/api/plugins/large_plugin/blob")
    assert response.status_code == 413
    assert response.json()["detail"] == "Plugin response exceeds maximum allowed size."
