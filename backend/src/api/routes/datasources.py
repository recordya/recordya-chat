"""Data sources API endpoints."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.dependencies import CurrentUser, DataSourceByPath
from src.core.registry import datasources

router = APIRouter()


class WelcomeSuggestion(BaseModel):
    """Welcome view suggestion."""
    text: str
    icon: str | None = None


class WelcomeInfo(BaseModel):
    """Welcome view metadata from manifest."""
    title: str | None = None
    description: str | None = None
    suggestions: list[WelcomeSuggestion] = []


class AgentInfo(BaseModel):
    """Agent UI metadata from manifest."""
    icon: str | None = None
    color: str | None = None


class DataSourceInfo(BaseModel):
    """Data source metadata."""
    name: str
    display_name: str
    description: str
    agent: AgentInfo | None = None
    welcome: WelcomeInfo | None = None


class DataSourceList(BaseModel):
    """List of data sources."""
    datasources: list[DataSourceInfo]


def _build_datasource_info(plugin: Any) -> DataSourceInfo:
    """Build DataSourceInfo from plugin attributes and manifest.
    
    Manifest is loaded by discovery and attached to plugin._manifest.
    Metadata (name, display_name, etc.) is already set on plugin from manifest.
    """
    manifest = getattr(plugin, "_manifest", None)
    
    agent_info = None
    welcome_info = None
    
    if manifest:
        # Agent UI info
        if "agent" in manifest:
            agent_info = AgentInfo(
                icon=manifest["agent"].get("icon"),
                color=manifest["agent"].get("color"),
            )
        
        # Welcome view info
        if "welcome" in manifest:
            welcome = manifest["welcome"]
            suggestions = []
            for s in welcome.get("suggestions", []):
                if isinstance(s, dict):
                    suggestions.append(WelcomeSuggestion(
                        text=s.get("text", ""),
                        icon=s.get("icon"),
                    ))
                else:
                    suggestions.append(WelcomeSuggestion(text=str(s)))
            
            welcome_info = WelcomeInfo(
                title=welcome.get("title"),
                description=welcome.get("description"),
                suggestions=suggestions,
            )
    
    return DataSourceInfo(
        name=plugin.name,
        display_name=plugin.display_name,
        description=plugin.description,
        agent=agent_info,
        welcome=welcome_info,
    )


class HealthResponse(BaseModel):
    """Health check response."""
    name: str
    healthy: bool


class SuggestionsResponse(BaseModel):
    """Suggestions response."""
    suggestions: list[str]


@router.get("", response_model=DataSourceList)
async def list_datasources(
    current_user: CurrentUser,
) -> DataSourceList:
    """List all available data sources.
    
    Returns metadata about each registered data source plugin,
    including manifest data (agent UI, welcome view).
    """
    plugins = datasources.get_all_instances()
    
    result = []
    for name, plugin in plugins.items():
        result.append(_build_datasource_info(plugin))
    
    return DataSourceList(datasources=result)


@router.get("/{datasource}", response_model=DataSourceInfo)
async def get_datasource(
    current_user: CurrentUser,
    plugin: DataSourceByPath,
) -> DataSourceInfo:
    """Get details for a specific data source."""
    return _build_datasource_info(plugin)


@router.get("/{datasource}/health", response_model=HealthResponse)
async def datasource_health(
    current_user: CurrentUser,
    plugin: DataSourceByPath,
) -> HealthResponse:
    """Health check for a specific data source."""
    healthy = await plugin.health_check()
    return HealthResponse(name=plugin.name, healthy=healthy)


@router.get("/{datasource}/suggestions", response_model=SuggestionsResponse)
async def datasource_suggestions(
    current_user: CurrentUser,
    plugin: DataSourceByPath,
) -> SuggestionsResponse:
    """Get example prompts/suggestions for a specific data source."""
    suggestions = plugin.get_suggestions()
    return SuggestionsResponse(suggestions=suggestions)
