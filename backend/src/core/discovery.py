"""Plugin discovery and loading."""

import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from .exceptions import AppException
from .global_tools import GlobalToolError, get_global_tool_registry
from .protocols import (
    BasePlugin,
    ChatAccessGuard,
    HttpRoutablePlugin,
    ToolSurface,
    UserLifecycleHook,
)
from src.plugin_sdk.manifest import PluginManifest

logger = logging.getLogger(__name__)


class PluginLoadError(AppException):
    """Raised when a plugin fails to load."""
    pass


class PluginDiscovery:
    """Discovers and loads plugin implementations.
    
    Supports two discovery mechanisms:
    1. Entry points (for installed packages)
    2. Local plugins/ folder (for development)
    """

    ENTRY_POINT_GROUP = "nexo.datasources"

    def __init__(self, plugins_dir: Path | None = None):
        """Initialize discovery.
        
        Args:
            plugins_dir: Optional path to plugins folder for dev loading
        """
        self.plugins_dir = plugins_dir
        self._plugins: dict[str, BasePlugin] = {}
        self._only: frozenset[str] | None = None

    async def discover_and_load(
        self,
        configs: dict[str, dict[str, Any]] | None = None,
        only: list[str] | None = None,
    ) -> dict[str, BasePlugin]:
        """Discover all plugins and initialize them.

        Args:
            configs: Optional dict of plugin configs by name
            only: If provided, only load plugins whose id is in this list.
                  Other discovered plugins are skipped before initialization.

        Returns:
            Dictionary of loaded plugins by name
        """
        configs = configs or {}
        self._only = frozenset(only) if only else None

        try:
            # 1. Discover from entry points
            await self._discover_entry_points(configs)

            # 2. Discover from plugins folder
            if self.plugins_dir and self.plugins_dir.exists():
                await self._discover_folder(configs)

            # Fail fast when a loaded plugin requires a global tool nobody provides
            self._validate_required_global_tools()
        except (GlobalToolError, PluginLoadError):
            # Hard discovery/config errors abort startup; do not leave partially
            # loaded plugins or stale global tool registrations behind.
            await self.shutdown_all()
            raise
        finally:
            self._only = None

        return self._plugins

    async def _discover_entry_points(self, configs: dict[str, dict[str, Any]]) -> None:
        """Load plugins from entry points."""
        try:
            if sys.version_info >= (3, 10):
                from importlib.metadata import entry_points
                eps = entry_points(group=self.ENTRY_POINT_GROUP)
            else:
                from importlib.metadata import entry_points
                eps = entry_points().get(self.ENTRY_POINT_GROUP, [])

            for ep in eps:
                try:
                    plugin_class = ep.load()
                    await self._load_plugin(plugin_class, configs)
                except (GlobalToolError, PluginLoadError):
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to load entry point '{ep.name}': {e}", exc_info=True
                    )

        except (GlobalToolError, PluginLoadError):
            raise
        except Exception as e:
            logger.debug(f"Entry point discovery failed: {e}")

    async def _discover_folder(self, configs: dict[str, dict[str, Any]]) -> None:
        """Load plugins from plugins/ folder.
        
        Supports two structures:
        1. Unified: plugins/my_plugin/backend/ (new architecture)
        2. Legacy: plugins/my_plugin/ with __init__.py directly
        """
        if not self.plugins_dir:
            return

        # Add plugins dir to sys.path for imports
        plugins_parent = str(self.plugins_dir.parent)
        if plugins_parent not in sys.path:
            sys.path.insert(0, plugins_parent)

        for item in self.plugins_dir.iterdir():
            try:
                if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
                    await self._load_from_file(item, configs)
                elif item.is_dir():
                    # Check for unified structure: plugins/my_plugin/backend/
                    backend_dir = item / "backend"
                    if backend_dir.is_dir() and (backend_dir / "__init__.py").exists():
                        await self._load_from_unified_package(item, configs)
                    # Legacy structure: plugins/my_plugin/__init__.py
                    elif (item / "__init__.py").exists():
                        await self._load_from_package(item, configs)
            except (GlobalToolError, PluginLoadError):
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to load plugin from '{item}': {e}", exc_info=True
                )

    async def _load_from_file(self, path: Path, configs: dict[str, dict[str, Any]]) -> None:
        """Load plugin from a single .py file."""
        module_name = f"plugins.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find and register access guards and HTTP routers
        self._register_access_guards(module, path.stem)
        self._register_http_routers(module, path.stem)
        self._register_user_lifecycle_hooks(module, path.stem)

        # Find BasePlugin subclass
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BasePlugin)
                and attr is not BasePlugin
            ):
                await self._load_plugin(attr, configs)

    async def _load_from_package(self, path: Path, configs: dict[str, dict[str, Any]]) -> None:
        """Load plugin from a package directory (legacy structure)."""
        package_name = path.name

        # Import the package properly using importlib
        try:
            # Try to import as a regular package
            module = importlib.import_module(f"plugins.{package_name}")

            # Find and register access guards and HTTP routers
            self._register_access_guards(module, package_name)
            self._register_http_routers(module, package_name)
            self._register_user_lifecycle_hooks(module, package_name)

            # Find BasePlugin subclass in module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                ):
                    await self._load_plugin(attr, configs)

        except ImportError as e:
            logger.warning(
                f"Failed to import plugin package '{package_name}': {e}", exc_info=True
            )

    async def _load_from_unified_package(self, path: Path, configs: dict[str, dict[str, Any]]) -> None:
        """Load plugin from unified structure: plugins/my_plugin/backend/."""
        package_name = path.name
        backend_path = path / "backend"

        # Add the plugin's backend dir to sys.path
        plugin_parent = str(path)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)

        try:
            # Import as plugins.{name}.backend
            module = importlib.import_module(f"plugins.{package_name}.backend")

            # Find and register access guards and HTTP routers
            self._register_access_guards(module, package_name)
            self._register_http_routers(module, package_name)
            self._register_user_lifecycle_hooks(module, package_name)

            # Find BasePlugin subclass in module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                ):
                    await self._load_plugin(attr, configs)

        except ImportError as e:
            logger.warning(
                f"Failed to import unified plugin '{package_name}': {e}", exc_info=True
            )

    @staticmethod
    def _register_access_guards(module: Any, package_name: str) -> None:
        """Find and register ChatAccessGuard implementations from a plugin module."""
        from .registry import access_guards

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and attr is not ChatAccessGuard
                and not getattr(attr, "_is_protocol", False)
                and hasattr(attr, "check_access")
                and hasattr(attr, "get_access_info")
            ):
                guard_id = f"{package_name}:{attr_name}"
                if not access_guards.has_instance(guard_id):
                    access_guards.register_instance(guard_id, attr())
                    logger.info(f"Access guard '{guard_id}' registered")

    @staticmethod
    def _register_http_routers(module: Any, package_name: str) -> None:
        """Find and register HttpRoutablePlugin implementations (non-BasePlugin).

        This allows HTTP-only endpoints without full plugin infrastructure.
        """
        from .registry import http_routers

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and not issubclass(attr, BasePlugin)  # Skip BasePlugin subclasses
                and isinstance(attr, type)
                and hasattr(attr, "get_api_router")
                and hasattr(attr, "get_api_auth_mode")
                and hasattr(attr, "name")
            ):
                try:
                    instance = attr()
                    if isinstance(instance, HttpRoutablePlugin):
                        router_id = getattr(instance, "name", f"{package_name}:{attr_name}")
                        if not http_routers.has_instance(router_id):
                            http_routers.register_instance(router_id, instance)
                            logger.info(f"HTTP router '{router_id}' registered")
                except Exception as e:
                    logger.warning(f"Failed to instantiate HTTP router {attr_name}: {e}")

    @staticmethod
    def _register_user_lifecycle_hooks(module: Any, package_name: str) -> None:
        """Find and register UserLifecycleHook implementations from a plugin module."""
        from .registry import user_lifecycle_hooks

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and attr is not UserLifecycleHook
                and not getattr(attr, "_is_protocol", False)
                and hasattr(attr, "on_user_created")
                and hasattr(attr, "on_user_activated")
                and hasattr(attr, "on_user_deactivated")
            ):
                hook_id = f"{package_name}:{attr_name}"
                if not user_lifecycle_hooks.has_instance(hook_id):
                    try:
                        user_lifecycle_hooks.register_instance(hook_id, attr())
                        logger.info(f"User lifecycle hook '{hook_id}' registered")
                    except Exception as e:
                        logger.warning(f"Failed to instantiate user lifecycle hook {attr_name}: {e}")

    def _load_manifest(self, plugin_class: type) -> dict[str, Any] | None:
        """Load manifest.yaml from plugin module directory.

        Manifest is the single source of truth for plugin metadata.
        Validation is delegated to the ``PluginManifest`` Pydantic model;
        an invalid manifest is a hard configuration error that raises
        ``PluginLoadError`` and aborts startup.
        """
        try:
            module = sys.modules.get(plugin_class.__module__)
            if not (module and hasattr(module, "__file__") and module.__file__):
                return None

            manifest_path = Path(module.__file__).parent / "manifest.yaml"
            if not manifest_path.exists():
                return None

            with open(manifest_path) as f:
                raw_manifest = yaml.safe_load(f) or {}

            manifest = PluginManifest.model_validate(raw_manifest)
            return manifest.model_dump(mode="python")
        except ValidationError as exc:
            raise PluginLoadError(
                f"Invalid manifest.yaml for {plugin_class.__name__}: {exc}"
            ) from exc
        except PluginLoadError:
            raise
        except Exception as e:
            logger.debug(f"Failed to load manifest for {plugin_class.__name__}: {e}")
        return None

    async def _load_plugin(
        self,
        plugin_class: type,
        configs: dict[str, dict[str, Any]],
    ) -> None:
        """Instantiate and initialize a plugin.
        
        Steps:
        1. Instantiate plugin
        2. Load manifest and set metadata
        3. Validate protocol version
        4. Load configuration
        5. Initialize plugin
        6. Health check
        7. Register
        """
        try:
            # Instantiate
            plugin = plugin_class()

            # Load manifest and set metadata (manifest is source of truth)
            manifest = self._load_manifest(plugin_class)
            if manifest:
                plugin._manifest = manifest
                # Override metadata from manifest
                if manifest.get("id"):
                    plugin.name = manifest["id"]
                if manifest.get("name"):
                    plugin.display_name = manifest["name"]
                if manifest.get("description"):
                    plugin.description = manifest["description"]
            # Skip disabled plugins (manifest.enabled == false)
            if manifest and manifest.get("enabled") is False:
                logger.info(f"Plugin '{manifest.get('id', plugin_class.__name__)}' disabled in manifest, skipping")
                return

            # Get name and validate
            name = getattr(plugin, "name", None)
            if not name:
                logger.warning(f"Plugin {plugin_class.__name__} has no name, skipping")
                return

            if name in self._plugins:
                logger.warning(f"Plugin '{name}' already loaded, skipping duplicate")
                return

            # Skip plugins not in the 'only' filter (before initialization)
            if self._only and name not in self._only:
                logger.debug(f"Plugin '{name}' skipped (not in 'only' filter)")
                return

            # Load config
            config = await self._load_config(name, plugin_class, configs)

            # Initialize
            logger.info(f"Initializing plugin '{name}'")
            await plugin.initialize(config)

            # Health check
            if not await plugin.health_check():
                logger.warning(f"Plugin '{name}' failed health check, skipping")
                await plugin.shutdown()
                return

            # Register contributed global tools (fail-fast on collisions)
            try:
                self._register_global_tools(name, plugin)
            except Exception:
                await plugin.shutdown()
                raise

            # Register
            self._plugins[name] = plugin
            logger.info(f"Plugin '{name}' loaded successfully")

        except (GlobalToolError, PluginLoadError):
            # Global-tool declaration errors are hard config errors: abort startup
            logger.exception(f"Failed to load plugin {plugin_class.__name__}")
            raise
        except Exception:
            logger.exception(f"Failed to load plugin {plugin_class.__name__}")

    @staticmethod
    def _load_plugin_env(plugin_dir: Path) -> dict[str, str]:
        """Load variables from a .env file in the plugin directory.

        Returns a dict of key-value pairs parsed from the file.
        Lines starting with # and blank lines are ignored.
        Values are not added to os.environ — used only for local substitution.
        """
        env_file = plugin_dir / ".env"
        if not env_file.exists():
            return {}
        result: dict[str, str] = {}
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
        return result

    @staticmethod
    def _expand_vars(content: str, extra: dict[str, str]) -> str:
        """Expand $VAR and ${VAR} placeholders using os.environ merged with extra."""
        import string
        mapping = {**os.environ, **extra}
        return string.Template(content).safe_substitute(mapping)

    async def _load_config(
        self,
        name: str,
        plugin_class: type,
        configs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Load configuration for a plugin.

        Priority:
        1. Explicit config passed to discover_and_load()
        2. config.yaml in plugin package (with optional sibling .env for secrets)
        3. {name}.config.yaml in plugins folder
        4. Empty dict (plugin uses defaults)

        Values in config.yaml may use $VAR or ${VAR} syntax. Variables are
        resolved from the plugin's own .env file first, then from os.environ.
        """
        # Explicit config
        if name in configs:
            return configs[name]

        # Look for config.yaml in plugin module
        try:
            module = sys.modules.get(plugin_class.__module__)
            if module and hasattr(module, "__file__") and module.__file__:
                module_dir = Path(module.__file__).parent
                config_file = module_dir / "config.yaml"
                if config_file.exists():
                    plugin_env = self._load_plugin_env(module_dir)
                    with open(config_file) as f:
                        return yaml.safe_load(self._expand_vars(f.read(), plugin_env)) or {}
        except Exception:
            pass

        # Look for {name}.config.yaml in plugins folder
        if self.plugins_dir:
            config_file = self.plugins_dir / f"{name}.config.yaml"
            if config_file.exists():
                with open(config_file) as f:
                    return yaml.safe_load(self._expand_vars(f.read(), {})) or {}

        return {}

    def _register_global_tools(self, name: str, plugin: BasePlugin) -> None:
        """Register manifest-declared global tools in the global registry.

        The manifest's ``provides_global_tools`` list is authoritative:
        each name must exist in the plugin's regular ``get_tools_definition()``,
        otherwise the plugin fails to load. Field types are guaranteed by the
        ``PluginManifest`` Pydantic model validated in ``_load_manifest``.
        """
        declared = plugin.get_manifest().get("provides_global_tools") or []
        if not declared:
            return

        registered = get_global_tool_registry().register_plugin(
            name, cast(ToolSurface, plugin), declared
        )
        logger.info(f"Plugin '{name}' registered global tools: {registered}")

    def _validate_required_global_tools(self) -> None:
        """Fail fast when required global tools are missing after discovery."""
        registry = get_global_tool_registry()
        missing: list[str] = []
        for name, plugin in self._plugins.items():
            required = plugin.get_manifest().get("requires_global_tools") or []
            absent = sorted(t for t in required if not registry.has_tool(t))
            if absent:
                missing.append(f"plugin '{name}' requires {', '.join(absent)}")
        if missing:
            raise PluginLoadError(
                "Missing required global tools: " + "; ".join(missing)
            )

    def get_plugin(self, name: str) -> BasePlugin | None:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        """List all loaded plugin names."""
        return list(self._plugins.keys())

    def get_all_plugins(self) -> dict[str, BasePlugin]:
        """Get all loaded plugins."""
        return self._plugins.copy()

    async def shutdown_all(self) -> None:
        """Shutdown all loaded plugins."""
        registry = get_global_tool_registry()
        for name, plugin in self._plugins.items():
            try:
                registry.unregister_plugin(name)
                await plugin.shutdown()
                logger.info(f"Plugin '{name}' shut down")
            except Exception as e:
                logger.error(f"Error shutting down plugin '{name}': {e}")
        self._plugins.clear()


# Global discovery instance
_discovery: PluginDiscovery | None = None


def get_discovery() -> PluginDiscovery:
    """Get the global discovery instance."""
    global _discovery
    if _discovery is None:
        _discovery = PluginDiscovery()
    return _discovery


def set_discovery(discovery: PluginDiscovery) -> None:
    """Set the global discovery instance."""
    global _discovery
    _discovery = discovery
