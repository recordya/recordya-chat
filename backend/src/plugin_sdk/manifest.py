"""Plugin manifest schema for plugin.json/manifest.yaml validation.

This module provides Pydantic models for validating plugin metadata.
Plugin metadata is informational, but the manifest must conform to this
schema — discovery rejects an invalid manifest.yaml and aborts startup
(a missing manifest is fine). Declared capabilities are not enforced at
runtime.

Usage:
    from src.plugin_sdk import PluginManifest
    
    # Load and validate manifest
    manifest = PluginManifest.model_validate(yaml.safe_load(manifest_file))
    
    # Access metadata
    print(manifest.name, manifest.id)
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentUIConfig(BaseModel):
    """Agent UI configuration for sidebar display."""
    
    icon: str = Field(default="box", description="Lucide icon name")
    color: str = Field(default="#6366F1", description="Brand color (hex)")


class WelcomeSuggestion(BaseModel):
    """A suggestion shown in the welcome view."""
    
    text: str = Field(..., description="Suggestion text")
    icon: str | None = Field(default=None, description="Optional Lucide icon")


class WelcomeConfig(BaseModel):
    """Welcome view configuration."""
    
    title: str = Field(..., description="Welcome title")
    description: str = Field(default="", description="Welcome description")
    suggestions: list[WelcomeSuggestion] = Field(
        default_factory=list,
        description="Example prompts/suggestions"
    )


class NavConfig(BaseModel):
    """Navigation rail configuration for ViewPlugin."""

    icon: str = Field(default="layout-grid", description="Lucide icon name for the rail")
    label: str = Field(..., description="Label shown in tooltip / nav")
    order: int = Field(default=10, description="Sort order in the rail (lower = higher)")


class FrontendConfig(BaseModel):
    """Frontend plugin integration configuration."""

    public_widgets: list[str] = Field(
        default_factory=list,
        description=(
            "Widget types exported as public. "
            "Widget types not listed here remain private to the plugin by default."
        ),
    )


class PluginManifest(BaseModel):
    """Plugin manifest schema.

    Defines metadata for a plugin. The metadata is informational, but the
    manifest itself must validate against this schema — discovery rejects
    an invalid manifest.yaml and aborts startup. Declared capabilities are
    not enforced at runtime.

    Example manifest.yaml (agent plugin):
        id: "my_plugin"
        name: "My Plugin"
        description: "Does something useful"

        agent:
          icon: "box"
          color: "#6366F1"

        welcome:
          title: "Welcome"
          description: "How can I help?"
          suggestions:
            - text: "Example query"
              icon: "search"

    Example manifest.yaml (view plugin):
        id: "my_view"
        name: "My View"
        description: "Custom UI view"

        nav:
          icon: "clipboard-list"
          label: "Orders"
          order: 10
    """

    # Required metadata
    id: str = Field(..., description="Unique plugin identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(default="", description="Plugin description")
    enabled: bool = Field(default=True, description="Whether the plugin is active; set to false to hide from UI and skip loading")

    # Optional UI configuration
    agent: AgentUIConfig = Field(
        default_factory=AgentUIConfig,
        description="Agent UI configuration (for ManagedPlugin / ExecutablePlugin)"
    )
    nav: NavConfig | None = Field(
        default=None,
        description="Navigation rail configuration (for ViewPlugin)"
    )
    welcome: WelcomeConfig | None = Field(
        default=None,
        description="Welcome view configuration"
    )
    frontend: FrontendConfig = Field(
        default_factory=FrontendConfig,
        description="Frontend integration and widget visibility configuration",
    )

    # Optional capabilities (informational, not enforced)
    capabilities: list[str] = Field(
        default_factory=list,
        description="Declared capabilities (e.g., 'database', 'llm', 'http')"
    )

    # Global tool contribution / consumption (validated at startup)
    provides_global_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Tool names this plugin exports to the global tool registry. "
            "Authoritative: each name must exist in the plugin's regular "
            "get_tools_definition(); validated fail-fast at plugin load."
        ),
    )
    requires_global_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Global tool names this plugin consumes. Exposed to the plugin's "
            "agent loop and validated fail-fast at startup."
        ),
    )

    # Extension point for custom metadata
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional plugin-specific metadata"
    )

    model_config = ConfigDict(extra="allow")  # Allow additional fields not in schema

