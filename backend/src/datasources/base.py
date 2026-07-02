"""Base class for SQL data source plugins.

DEPRECATED: Import from src.plugin_sdk instead:
    from src.plugin_sdk import BaseSQLPlugin

This module re-exports from plugin_sdk for backwards compatibility.
"""

# Re-export from plugin_sdk for backwards compatibility
from src.plugin_sdk.sql import BaseSQLPlugin, BaseDataSourcePlugin

__all__ = ["BaseSQLPlugin", "BaseDataSourcePlugin"]
