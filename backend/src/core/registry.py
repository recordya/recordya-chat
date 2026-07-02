"""Plugin registry for managing connectors, providers, and datasources."""

from typing import Any, Callable, Generic, TypeVar

from .exceptions import AppException

T = TypeVar("T")


class PluginRegistry(Generic[T]):
    """Generic registry for plugin classes and instances."""

    def __init__(self) -> None:
        self._classes: dict[str, type[T]] = {}
        self._instances: dict[str, T] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        """Decorator to register a plugin class."""
        def decorator(cls: type[T]) -> type[T]:
            if name in self._classes:
                raise AppException(f"Plugin '{name}' is already registered")
            self._classes[name] = cls
            return cls
        return decorator

    def register_class(self, name: str, cls: type[T]) -> None:
        """Register a plugin class directly."""
        if name in self._classes:
            raise AppException(f"Plugin '{name}' is already registered")
        self._classes[name] = cls

    def register_instance(self, name: str, instance: T) -> None:
        """Register a pre-configured plugin instance."""
        self._instances[name] = instance

    def unregister_instance(self, name: str) -> None:
        """Unregister a plugin instance."""
        if name in self._instances:
            del self._instances[name]

    def create(self, name: str, **kwargs: Any) -> T:
        """Create a new instance of a registered plugin class."""
        if name not in self._classes:
            available = ", ".join(self._classes.keys()) or "none"
            raise AppException(f"Plugin '{name}' not found. Available: {available}")
        return self._classes[name](**kwargs)

    def get_instance(self, name: str) -> T:
        """Get a registered plugin instance."""
        if name not in self._instances:
            available = ", ".join(self._instances.keys()) or "none"
            raise AppException(f"Instance '{name}' not found. Available: {available}")
        return self._instances[name]

    def get_class(self, name: str) -> type[T]:
        """Get a registered plugin class."""
        if name not in self._classes:
            available = ", ".join(self._classes.keys()) or "none"
            raise AppException(f"Plugin '{name}' not found. Available: {available}")
        return self._classes[name]

    def list_classes(self) -> list[str]:
        """List all registered plugin class names."""
        return list(self._classes.keys())

    def list_instances(self) -> list[str]:
        """List all registered instance names."""
        return list(self._instances.keys())

    def has_class(self, name: str) -> bool:
        """Check if a plugin class is registered."""
        return name in self._classes

    def has_instance(self, name: str) -> bool:
        """Check if an instance is registered."""
        return name in self._instances

    def get_all_instances(self) -> dict[str, T]:
        """Get all registered instances."""
        return self._instances.copy()

    def clear(self) -> None:
        """Clear all registrations."""
        self._classes.clear()
        self._instances.clear()


# Global registries
from .protocols import (
    BasePlugin,
    ChatAccessGuard,
    HttpRoutablePlugin,
    LLMProvider,
    UserLifecycleHook,
    ViewPlugin,
)

llm_providers: PluginRegistry[LLMProvider] = PluginRegistry()
datasources: PluginRegistry[BasePlugin] = PluginRegistry()
view_plugins: PluginRegistry[ViewPlugin] = PluginRegistry()
access_guards: PluginRegistry[ChatAccessGuard] = PluginRegistry()
http_routers: PluginRegistry[HttpRoutablePlugin] = PluginRegistry()
user_lifecycle_hooks: PluginRegistry[UserLifecycleHook] = PluginRegistry()
