"""View plugins API endpoints.

Returns metadata about registered ViewPlugin instances so the frontend
can dynamically add icons to the navigation rail.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.dependencies import CurrentUser
from src.core.registry import view_plugins

router = APIRouter()


class ViewNavInfo(BaseModel):
    """Navigation rail metadata for a single ViewPlugin."""

    id: str
    name: str
    description: str
    icon: str
    label: str
    order: int


class ViewList(BaseModel):
    """List of view plugins."""

    views: list[ViewNavInfo]


def _build_view_info(plugin: Any) -> ViewNavInfo:
    """Build ViewNavInfo from plugin attributes and manifest."""
    manifest = getattr(plugin, "_manifest", None) or {}
    nav = manifest.get("nav") or {}

    return ViewNavInfo(
        id=plugin.name,
        name=getattr(plugin, "display_name", plugin.name),
        description=getattr(plugin, "description", ""),
        icon=nav.get("icon", "layout-grid"),
        label=nav.get("label", getattr(plugin, "display_name", plugin.name)),
        order=nav.get("order", 10),
    )


@router.get("", response_model=ViewList)
async def list_views(
    current_user: CurrentUser,
) -> ViewList:
    """List all registered view plugins.

    Returns navigation metadata so the frontend can render icons
    in the navigation rail and register routes dynamically.
    """
    plugins = view_plugins.get_all_instances()
    return ViewList(views=[_build_view_info(p) for p in plugins.values()])
