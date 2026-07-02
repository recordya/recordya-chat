"""Core module - configuration, protocols, registry."""

from .config import settings
from .protocols import LLMProvider, ViewPlugin
from .registry import llm_providers

__all__ = [
    "settings",
    "LLMProvider",
    "ViewPlugin",
    "llm_providers",
]
